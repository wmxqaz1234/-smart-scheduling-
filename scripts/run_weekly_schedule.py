#!/usr/bin/env python3
"""
每周智能排班 - 完整流程脚本

从 config.json 读取配置，查询简道云数据，调用 scheduler.py 生成排班，写回结果。

用法:
    python run_weekly_schedule.py [--week-offset N]
    
参数:
    --week-offset N  排班周偏移量，0=本周，1=下周（默认1）
"""

import json
import sys
import os
import argparse
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# 添加脚本目录到路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from jdy_client import JDYClient
from tz_util import now_bjt, bj_date_to_utc_midnight


def load_config():
    """加载配置"""
    config_path = SCRIPT_DIR.parent / "config.json"
    if not config_path.exists():
        print(f"ERROR: 配置文件不存在: {config_path}", file=sys.stderr)
        sys.exit(1)
    
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    
    api_key = cfg.get("api_key", "")
    if not api_key:
        print("ERROR: API Key 未配置，请检查 config.json", file=sys.stderr)
        sys.exit(1)
    
    return cfg, api_key


def get_week_dates(week_offset=1):
    """获取目标周的周一和周日日期（北京时间）"""
    today = now_bjt()
    # 计算本周一
    this_monday = today - timedelta(days=today.weekday())
    # 目标周一
    target_monday = this_monday + timedelta(weeks=week_offset)
    target_sunday = target_monday + timedelta(days=6)
    
    return target_monday.strftime("%Y-%m-%d"), target_sunday.strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser(description="每周智能排班")
    parser.add_argument("--week-offset", type=int, default=1, help="排班周偏移量，0=本周，1=下周")
    args = parser.parse_args()
    
    # 1. 加载配置
    print("=== 加载配置 ===")
    cfg, api_key = load_config()
    app_id = cfg["app_id"]
    client = JDYClient(api_key)
    
    # 2. 计算排班周期
    start_date, end_date = get_week_dates(args.week_offset)
    week_num = datetime.strptime(start_date, "%Y-%m-%d").isocalendar()[1]
    period = f"{datetime.strptime(start_date, '%Y-%m-%d').year}-W{week_num:02d}"
    print(f"排班周期: {period} ({start_date} ~ {end_date})")
    
    # 3. 查询数据
    print("\n=== 查询数据 ===")
    
    # 查询在职员工
    emp = cfg["tables"]["employee"]
    employees_raw = client.list_data(
        app_id, emp["entry_id"],
        fields=[emp["fields"]["name"], emp["fields"]["employee_id"], 
                emp["fields"]["skill_level"], emp["fields"]["max_weekly_days"],
                emp["fields"]["status"]],
        filter_cond={
            "rel": "and",
            "cond": [{"field": emp["fields"]["status"], "type": "text", "method": "eq", "value": ["在职"]}]
        }
    )
    print(f"在职员工: {len(employees_raw)} 人")
    if not employees_raw:
        print("ERROR: 无在职员工数据，请检查员工信息表是否有状态为'在职'的记录", file=sys.stderr)
        sys.exit(1)
    
    # 查询班次模板
    shift = cfg["tables"]["shift_template"]
    shifts_raw = client.list_data(app_id, shift["entry_id"])
    print(f"班次模板: {len(shifts_raw)} 个")
    if not shifts_raw:
        print("ERROR: 无班次模板数据，请检查班次模板表是否有记录", file=sys.stderr)
        sys.exit(1)
    
    # 查询排班规则（非必须，缺失时使用默认值）
    rule = cfg["tables"]["schedule_rule"]
    rules_raw = client.list_data(app_id, rule["entry_id"])
    print(f"排班规则: {len(rules_raw)} 条")
    
    # 请假查询：排班生成暂不考虑请假，请假通过独立流程处理
    # （候选名单由 webhook 管道实时推荐，排班调整由 scheduler.py adjust 模式执行）
    leaves = []
    
    # 4. 准备 scheduler.py 输入数据
    print("\n=== 准备数据 ===")
    
    employees = [
        {
            "id": e.get(emp["fields"]["employee_id"], ""),
            "name": e.get(emp["fields"]["name"], ""),
            "skill_level": e.get(emp["fields"]["skill_level"], "中级"),
            "max_weekly_days": e.get(emp["fields"]["max_weekly_days"], 5)
        }
        for e in employees_raw
    ]
    
    # 构建 data_id 映射（用于写入关联字段）
    emp_id_to_data_id = {e.get(emp["fields"]["employee_id"], ""): e.get("_id", "") for e in employees_raw}
    
    shifts = [
        {
            "id": s.get("_id", ""),
            "name": s.get(shift["fields"]["name"], ""),
            "start_time": s.get(shift["fields"]["start_time"], ""),
            "end_time": s.get(shift["fields"]["end_time"], ""),
            "required_count": s.get(shift["fields"]["required_count"], 1),
            "required_skill": s.get(shift["fields"]["required_skill"], "中级")
        }
        for s in shifts_raw
    ]
    
    # 构建班次 data_id 映射（用于写入关联字段）
    shift_name_to_data_id = {s.get(shift["fields"]["name"], ""): s.get("_id", "") for s in shifts_raw}
    
    rules = [
        {
            "type": r.get(rule["fields"]["rule_type"], ""),
            "value": r.get(rule["fields"]["param_value"], 0)
        }
        for r in rules_raw
    ]
    
    # 生成日期列表
    dates = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    while current <= end_dt:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    
    input_data = {
        "employees": employees,
        "shifts": shifts,
        "rules": rules,
        "leaves": leaves,
        "dates": dates
    }
    
    input_path = SCRIPT_DIR.parent / f"schedule_input_{period}.json"
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(input_data, f, ensure_ascii=False, indent=2)
    print(f"输入数据已保存: {input_path}")
    
    # 5. 调用 scheduler.py
    print("\n=== 运行排班算法 ===")
    output_path = SCRIPT_DIR.parent / f"schedule_output_{period}.json"
    result = subprocess.run(
        ["python", str(SCRIPT_DIR / "scheduler.py"), "generate", str(input_path), str(output_path)],
        capture_output=False
    )
    if result.returncode != 0:
        print(f"ERROR: 排班算法执行失败 (exit code: {result.returncode})", file=sys.stderr)
        sys.exit(1)
    
    if not output_path.exists():
        print("ERROR: 排班算法执行失败", file=sys.stderr)
        sys.exit(1)
    
    with open(output_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    
    # scheduler.py 输出格式：{"schedule": [...], "summary": {...}}
    schedule_list = result.get("schedule", [])
    print(f"\n排班完成: {len(schedule_list)} 条排班记录")
    
    # 6. 写回简道云
    print("\n=== 写入简道云 ===")
    sch = cfg["tables"]["schedule"]
    
    data_list = []
    for assignment in schedule_list:
        emp_id = assignment["employee_id"]
        shift_name = assignment["shift_name"]
        
        # 关联字段需要写入 data_id 格式：{"value": "data_id_string"}
        emp_data_id = emp_id_to_data_id.get(emp_id, "")
        shift_data_id = shift_name_to_data_id.get(shift_name, "")
        
        data = {
            sch["fields"]["period"]: {"value": period},
            sch["fields"]["date"]: {"value": bj_date_to_utc_midnight(assignment["date"])},
            sch["fields"]["employee_id"]: {"value": emp_id},
            sch["fields"]["status"]: {"value": "待确认"}
        }
        
        # 员工关联字段：{"value": "data_id"}
        if emp_data_id and "employee" in sch["fields"]:
            data[sch["fields"]["employee"]] = {"value": emp_data_id}
        
        # 班次关联字段：{"value": "data_id"}
        if shift_data_id and "shift" in sch["fields"]:
            data[sch["fields"]["shift"]] = {"value": shift_data_id}
        
        data_list.append(data)
    
    write_result = client.batch_create_data(app_id, sch["entry_id"], data_list)
    success_count = write_result.get("created", 0)
    errors = write_result.get("errors", [])
    
    if errors:
        print(f"写入警告: {len(errors)} 个批次出错")
    
    print(f"写入成功: {success_count}/{len(schedule_list)}")
    
    # 7. 输出摘要
    print("\n" + "="*60)
    print("排班摘要")
    print("="*60)
    print(json.dumps({
        "success": True,
        "period": period,
        "date_range": f"{start_date} ~ {end_date}",
        "employee_count": len(employees),
        "shift_count": len(shifts),
        "assignment_count": len(schedule_list),
        "written_count": success_count,
        "satisfaction_rate": result.get("summary", {}).get("fill_rate", 0)
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
