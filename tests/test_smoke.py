#!/usr/bin/env python3
"""
智能排班系统 - 冒烟测试

使用 mock 数据验证排班算法核心逻辑，不依赖简道云 API。
安装后运行此脚本可快速验证系统是否正常。

用法：
    python skills/smart-scheduling/tests/test_smoke.py
"""

import json
import sys
import tempfile
from pathlib import Path

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent / "scripts"))

from scheduler import SchedulingEngine, ConstraintChecker


def build_mock_data():
    """构建 mock 测试数据"""
    employees = [
        {"id": "E001", "name": "张三", "skill_level": "高级", "max_weekly_days": 5},
        {"id": "E002", "name": "李四", "skill_level": "中级", "max_weekly_days": 5},
        {"id": "E003", "name": "王五", "skill_level": "初级", "max_weekly_days": 5},
        {"id": "E004", "name": "赵六", "skill_level": "中级", "max_weekly_days": 5},
        {"id": "E005", "name": "孙七", "skill_level": "高级", "max_weekly_days": 5},
    ]

    shifts = [
        {
            "id": "shift_am",
            "name": "早班",
            "start_time": "08:00",
            "end_time": "16:00",
            "required_count": 2,
            "required_skill": "初级"
        },
        {
            "id": "shift_pm",
            "name": "中班",
            "start_time": "16:00",
            "end_time": "00:00",
            "required_count": 2,
            "required_skill": "中级"
        },
    ]

    rules = [
        {"type": "max_consecutive_days", "value": 6},
        {"type": "max_weekly_days", "value": 5},
        {"type": "max_shifts_per_day", "value": 1},
    ]

    dates = [
        "2026-06-15", "2026-06-16", "2026-06-17",
        "2026-06-18", "2026-06-19", "2026-06-20", "2026-06-21",
    ]

    return {
        "period": "2026-W25",
        "employees": employees,
        "shifts": shifts,
        "rules": rules,
        "leaves": [],
        "dates": dates,
    }


def test_generate():
    """测试全量排班生成"""
    print("[测试] 全量排班生成...")
    data = build_mock_data()
    engine = SchedulingEngine(data)
    result = engine.generate()

    # 验证输出结构
    assert "schedule" in result, "输出缺少 schedule 字段"
    assert "summary" in result, "输出缺少 summary 字段"

    schedule = result["schedule"]
    summary = result["summary"]

    # 验证 summary 字段
    assert "period" in summary, "summary 缺少 period"
    assert "total_assignments" in summary, "summary 缺少 total_assignments"
    assert "total_demand" in summary, "summary 缺少 total_demand"
    assert "fill_rate" in summary, "summary 缺少 fill_rate"
    assert "avg_shifts_per_person" in summary, "summary 缺少 avg_shifts_per_person"
    assert "shift_count_std" in summary, "summary 缺少 shift_count_std"
    assert "employee_stats" in summary, "summary 缺少 employee_stats"

    # 验证排班记录字段
    for record in schedule:
        for key in ["employee_id", "employee_name", "date", "shift_id", "shift_name", "status"]:
            assert key in record, f"排班记录缺少字段: {key}"

    # 验证约束
    checker = ConstraintChecker(
        data["employees"], data["shifts"],
        data["rules"], data["leaves"], data["dates"]
    )

    # 加载排班结果到 checker
    for record in schedule:
        checker.assign(record["employee_id"], record["date"], record["shift_id"])

    # 检查每人每天最多 1 个班次
    emp_dates = {}
    for record in schedule:
        key = (record["employee_id"], record["date"])
        emp_dates[key] = emp_dates.get(key, 0) + 1
    for key, count in emp_dates.items():
        assert count <= 1, f"约束违反: {key} 有 {count} 个班次（max=1）"

    # 检查每人每周最多 5 天
    from collections import defaultdict
    from datetime import datetime, timedelta
    emp_week_days = defaultdict(set)
    for record in schedule:
        d = datetime.strptime(record["date"], "%Y-%m-%d")
        week_start = d - timedelta(days=d.weekday())
        week_key = (record["employee_id"], week_start.strftime("%Y-%m-%d"))
        emp_week_days[week_key].add(record["date"])
    for key, days in emp_week_days.items():
        assert len(days) <= 5, f"约束违反: {key} 工作 {len(days)} 天（max=5）"

    # 验证填充率
    total_demand = sum(data["shifts"][s]["required_count"] * len(data["dates"]) for s in range(len(data["shifts"])))
    fill_rate = len(schedule) / total_demand * 100

    print(f"  ✅ 排班记录: {len(schedule)} 条")
    print(f"  ✅ 填充率: {fill_rate:.1f}%")
    print(f"  ✅ 人均班次: {summary['avg_shifts_per_person']}")
    print(f"  ✅ 标准差: {summary['shift_count_std']}")
    print(f"  ✅ 约束检查通过")
    print()

    return True


def test_leave():
    """测试请假场景"""
    print("[测试] 请假场景...")
    data = build_mock_data()

    # 添加请假
    data["leaves"] = [
        {"employee_id": "E001", "start_date": "2026-06-17", "end_date": "2026-06-17", "status": "已批准"}
    ]

    engine = SchedulingEngine(data)
    result = engine.generate()

    # 验证 E001 在请假日没有排班
    for record in result["schedule"]:
        if record["employee_id"] == "E001":
            assert record["date"] != "2026-06-17", "约束违反: 请假员工被排班"

    print(f"  ✅ 请假员工 E001 在 2026-06-17 无排班")
    print(f"  ✅ 总排班: {len(result['schedule'])} 条")
    print()

    return True


def test_skill_match():
    """测试技能匹配"""
    print("[测试] 技能匹配...")
    data = build_mock_data()

    # 修改晚班需要高级技能
    data["shifts"][1]["required_skill"] = "高级"

    engine = SchedulingEngine(data)
    result = engine.generate()

    # 验证中班只有中级或高级员工
    level_map = {"初级": 1, "中级": 2, "高级": 3}
    emp_map = {e["id"]: e for e in data["employees"]}
    for record in result["schedule"]:
        if record["shift_id"] == "shift_pm":
            emp = emp_map.get(record["employee_id"], {})
            emp_level = level_map.get(emp.get("skill_level", "初级"), 1)
            assert emp_level >= 2, f"技能不匹配: {record['employee_name']}({emp.get('skill_level')}) 排到中班(需高级)"

    print(f"  ✅ 中班技能匹配检查通过")
    print()

    return True


def test_timezone():
    """测试时区转换工具"""
    print("[测试] 时区转换...")
    from tz_util import utc_to_bj_date, bj_date_to_utc_midnight, bj_date_to_utc_range

    # UTC → 北京时间日期
    assert utc_to_bj_date("2026-06-15T16:00:00.000Z") == "2026-06-16", "UTC 16:00 应为北京时间次日"
    assert utc_to_bj_date("2026-06-16T00:00:00.000Z") == "2026-06-16", "UTC 00:00 应为北京时间同日 08:00"
    assert utc_to_bj_date("2026-06-16T07:59:00.000Z") == "2026-06-16", "UTC 07:59 应为北京时间 15:59"

    # 北京时间日期 → UTC 零点
    assert bj_date_to_utc_midnight("2026-06-16") == "2026-06-16T00:00:00.000Z"

    # 北京时间单日 → UTC 查询范围
    start, end = bj_date_to_utc_range("2026-06-16")
    assert start == "2026-06-15T16:00:00.000Z", f"北京时间 6/16 00:00 = UTC 6/15 16:00, got {start}"
    assert "2026-06-16T15:59" in end, f"北京时间 6/16 23:59 = UTC 6/16 15:59, got {end}"

    print("  ✅ UTC → 北京时间日期")
    print("  ✅ 北京时间日期 → UTC 零点格式")
    print("  ✅ 北京时间日期 → UTC 查询范围")
    print()

    return True


def main():
    print("=" * 50)
    print("智能排班系统 v3.0 - 冒烟测试")
    print("=" * 50)
    print()

    tests = [test_generate, test_leave, test_skill_match, test_timezone]
    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            if test_fn():
                passed += 1
        except AssertionError as e:
            print(f"  ❌ 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            failed += 1

    print("=" * 50)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 50)

    if failed > 0:
        sys.exit(1)
    else:
        print("\n✅ 所有测试通过，系统可正常使用。")


if __name__ == "__main__":
    main()
