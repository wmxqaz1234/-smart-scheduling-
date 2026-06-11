#!/usr/bin/env python3
"""
智能排班系统 - 自动化管道创建脚本

从配置文件自动创建两个排班相关的自动化管道：
1. 请假候选名单查询（webhook 触发）
2. 每周智能排班（cron 触发）

用法:
    python create_pipelines.py --config skills/smart-scheduling/config.json
"""

import json
import argparse
import sys
from pathlib import Path

# 请假候选名单查询 - task_design
# 业务逻辑封装在 scripts/leave_candidates.py，task_design 只负责传参调用
# payload 字段映射从 config.json 的 webhook_payload_fields 读取，不硬编码 widget_id
LEAVE_TASK_DESIGN = """# 请假候选员工查询

简道云请假表提交 → Webhook 推送 → 调用脚本查询候选替班员工。

## 执行

使用 bash 执行以下命令（一条命令完成全部逻辑）：

```bash
python skills/smart-scheduling/scripts/leave_candidates.py --payload '{{payload}}'
```

脚本会自动完成：读取配置 → 查询在职员工 → 查询已排班员工 → 筛选候选名单 → 更新请假表子表单。

脚本从 config.json 的 `webhook_payload_fields` 读取字段映射，自动识别 payload 中的 widget_id，无需在 task_design 中硬编码。

## 输出解读

脚本输出 JSON，关键字段：
- `success`: 是否执行成功
- `leave_info`: 请假信息（员工、日期）
- `candidates`: 候选员工列表（姓名 + 工号）
- `statistics`: 统计（在职总数、已排班数、候选数）
- `subform_updated`: 子表单是否更新成功

## 异常处理
- 无候选员工时 `candidates` 为空数组
- API 失败时 `success` 为 false，`error` 包含错误信息
- 脚本内置重试机制，无需额外处理
"""

# 每周智能排班 - task_design
# 业务逻辑封装在 scripts/run_weekly_schedule.py，task_design 只负责调用
WEEKLY_TASK_DESIGN = """# 每周智能排班

自动为下周一~周日生成排班表，写入简道云排班结果表。

## 执行

使用 bash 执行以下命令（一条命令完成全部逻辑）：

```bash
python skills/smart-scheduling/scripts/run_weekly_schedule.py --week-offset 1
```

脚本会自动完成：读取配置 → 查询员工/班次/规则/请假 → 运行排班算法 → 写回简道云。

脚本从 config.json 读取所有配置和字段映射，无需在 task_design 中硬编码。

## 输出解读

脚本输出 JSON，关键字段：
- `success`: 是否执行成功
- `period`: 排班周期（如 2026-W25）
- `date_range`: 日期范围
- `employee_count`: 参与排班的员工数
- `assignment_count`: 生成的排班记录数
- `written_count`: 成功写入简道云的记录数
- `satisfaction_rate`: 班次满足率

## 异常处理
- 员工/班次/规则数据为空时，脚本会输出警告
- 排班算法失败时 `success` 为 false
- API 写入失败时会显示成功/失败数量
"""


def create_pipelines(config_path):
    """创建管道配置文件"""
    config_path = Path(config_path)
    output_dir = config_path.parent / "pipelines"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存 task_design 文件
    leave_task_path = output_dir / "leave-candidate-query-task.md"
    weekly_task_path = output_dir / "weekly-scheduling-task.md"
    
    leave_task_path.write_text(LEAVE_TASK_DESIGN, encoding="utf-8")
    weekly_task_path.write_text(WEEKLY_TASK_DESIGN, encoding="utf-8")
    
    print(f"✅ 管道任务设计文件已保存:")
    print(f"   - {leave_task_path}")
    print(f"   - {weekly_task_path}")
    
    # 保存管道元配置
    pipelines_meta = {
        "version": "2.0",
        "pipelines": [
            {
                "name": "leave-candidate-query",
                "display_name": "请假候选名单查询",
                "description": "简道云请假表提交后自动筛选可替班候选人并更新子表单",
                "trigger_config": {
                    "type": "webhook",
                    "timezone": "Asia/Shanghai"
                },
                "variables_schema": {
                    "config_path": {
                        "type": "string",
                        "default": str(config_path),
                        "label": "配置文件路径",
                        "description": "排班系统配置文件路径"
                    }
                },
                "execution_config": {
                    "max_iterations": 15,
                    "timeout_minutes": 10
                },
                "task_design_file": str(leave_task_path.relative_to(config_path.parent))
            },
            {
                "name": "weekly-scheduling",
                "display_name": "每周智能排班",
                "description": "每周五自动生成下周排班表，写入简道云排班结果表",
                "trigger_config": {
                    "type": "cron",
                    "cron_expr": "0 16 * * 5",
                    "timezone": "Asia/Shanghai"
                },
                "variables_schema": {
                    "config_path": {
                        "type": "string",
                        "default": str(config_path),
                        "label": "配置文件路径",
                        "description": "排班系统配置文件路径"
                    }
                },
                "execution_config": {
                    "max_iterations": 25,
                    "timeout_minutes": 15
                },
                "task_design_file": str(weekly_task_path.relative_to(config_path.parent))
            }
        ]
    }
    
    meta_path = output_dir / "pipelines-meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(pipelines_meta, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 管道元配置已保存: {meta_path}")
    print(f"\n📝 目标 Agent 安装后，读取 pipelines/pipelines-meta.json 即可创建管道")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="智能排班系统 - 管道配置导出")
    parser.add_argument("--config", default="skills/smart-scheduling/config.json",
                        help="配置文件路径")
    parser.add_argument("--output", help="输出目录（默认在 config.json 同级目录）")
    
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    output_dir = args.output
    if output_dir:
        output_dir = Path(output_dir)
    else:
        output_dir = config_path.parent
    
    print(f"🚀 开始导出管道配置...")
    print(f"   配置文件: {config_path}")
    print(f"   输出目录: {output_dir}")
    print()
    
    success = create_pipelines(config_path)
    
    if success:
        print("\n🎉 管道配置导出完成！")
    else:
        print("\n❌ 管道配置导出失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
