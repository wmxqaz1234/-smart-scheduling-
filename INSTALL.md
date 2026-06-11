# 智能排班系统 v3.0 - 安装指南

## 给 Agent 的安装指令

当你收到这个技能包时，请按以下步骤自动安装：

### 一键安装（推荐）

```bash
python skills/smart-scheduling/scripts/install.py \
  --app-id YOUR_APP_ID \
  --api-key YOUR_API_KEY
```

脚本会自动完成：
1. ✅ 连接简道云应用，遍历表单和字段
2. ✅ 通过字段 label 自动识别业务表和字段
3. ✅ 生成 `config.json`（所有 widget_id 映射）
4. ✅ 输出管道创建指令

### 手动安装（可选）

如果一键安装失败，可分步执行：

```bash
# 1. 提取配置（需要简道云 app_id 和 API Key）
python skills/smart-scheduling/scripts/init_config.py \
  --app-id YOUR_APP_ID \
  --api-key YOUR_API_KEY

# 2. 按 SKILL.md 中的"创建自动化管道"章节手动创建管道
```

## 管道创建

安装完成后，Agent 需要读取 `skills/smart-scheduling/pipelines/pipelines-meta.json`，然后调用 `automation(action="create")` 创建两个管道：

1. **每周智能排班** - cron 触发（每周五 16:00）
2. **请假候选名单查询** - webhook 触发

## 验证安装

安装完成后，检查以下文件是否存在：

```
skills/smart-scheduling/
├── SKILL.md                    ← 技能文档（系统概述、工作流、字段定义）
├── config.json                 ← 配置文件（init_config.py 自动生成）
├── INSTALL.md                  ← 本文件
├── requirements.txt            ← Python 依赖
├── pipelines/                  ← 管道配置
│   ├── pipelines-meta.json     ← 管道元配置
│   ├── weekly-schedule-task.md ← 每周排班任务设计
│   └── leave-candidates-task.md← 请假候选任务设计
├── scripts/
│   ├── scheduler.py            ← 排班算法引擎（generate / adjust 两种模式）
│   ├── jdy_client.py           ← 简道云 API 客户端
│   ├── leave_candidates.py     ← 请假候选员工查询脚本
│   ├── run_weekly_schedule.py  ← 每周排班完整流程脚本
│   ├── init_config.py          ← 配置自动提取脚本
│   └── install.py              ← 一键安装脚本
└── tests/
    └── test_smoke.py           ← 冒烟测试
```

### 快速验证

```bash
# 运行冒烟测试，验证算法核心逻辑
python skills/smart-scheduling/tests/test_smoke.py
```

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| 表单匹配失败 | 检查表单名称是否包含关键词（员工、班次、规则、排班、请假） |
| API Key 无效 | 在简道云后台重新生成 API Key |
| 管道创建失败 | 检查 pipelines-meta.json 格式是否正确 |
| 候选名单为空 | 检查排班结果表是否有该日期的排班数据 |
| 排班填充率低 | 增加员工数量或降低班次需求人数 |

## 技术支持

查看 `SKILL.md` 获取完整的系统架构、数据模型、算法说明和注意事项。
