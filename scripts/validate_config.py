#!/usr/bin/env python3
"""
智能排班系统 - 配置验证脚本

用途：客户建完简道云表单后，运行此脚本检查表结构是否正确。
会逐项验证 5 张表是否存在、必填字段是否齐全、字段类型是否正确、
单选选项值是否匹配。输出清晰的 PASS/FAIL 报告。

用法：
    python validate_config.py --app-id YOUR_APP_ID --api-key YOUR_API_KEY
    
或者先跑 init_config.py 生成 config.json 后：
    python validate_config.py --config config.json
"""

import json
import argparse
import sys
from typing import Dict, List, Tuple

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://api.jiandaoyun.com"

# ============================================================
# 预期的表结构定义
# ============================================================

EXPECTED_TABLES = {
    "employee": {
        "display_name": "员工信息表",
        "name_keywords": ["员工信息表", "员工表", "employee"],
        "required_fields": {
            "name": {"labels": ["姓名", "员工姓名"], "type": "text"},
            "employee_id": {"labels": ["工号", "员工工号", "员工编号"], "type": "text"},
            "department": {"labels": ["部门", "所属部门"], "type": "text"},
            "position": {"labels": ["岗位", "职位"], "type": "text"},
            "skill_level": {"labels": ["技能等级", "技能", "技能级别"], "type": "select",
                            "options": ["初级", "中级", "高级"]},
            "status": {"labels": ["状态", "员工状态", "在职状态"], "type": "select",
                       "options": ["在职", "离职", "休假"]},
        },
        "optional_fields": {
            "max_weekly_days": {"labels": ["每周最大天数", "最大周天数", "周最大工作天数"], "type": "number"},
        }
    },
    "shift_template": {
        "display_name": "班次模板表",
        "name_keywords": ["班次模板表", "班次表", "shift", "班次"],
        "required_fields": {
            "name": {"labels": ["班次名称", "班次名", "名称"], "type": "text"},
            "start_time": {"labels": ["开始时间", "上班时间"], "type": "text"},
            "end_time": {"labels": ["结束时间", "下班时间"], "type": "text"},
            "duration": {"labels": ["时长", "时长(小时)", "工时"], "type": "number"},
            "required_count": {"labels": ["所需人数", "需求人数", "人数"], "type": "number"},
            "shift_type": {"labels": ["班次类型", "类型"], "type": "select",
                           "options": ["早班", "中班", "晚班", "全天"]},
        },
        "optional_fields": {
            "required_skill": {"labels": ["所需技能", "最低技能", "技能要求"], "type": "select",
                               "options": ["无", "初级", "中级", "高级"]},
        }
    },
    "schedule_rule": {
        "display_name": "排班规则表",
        "name_keywords": ["排班规则表", "规则表", "rule", "排班规则"],
        "required_fields": {
            "rule_name": {"labels": ["规则名称", "名称"], "type": "text"},
            "rule_type": {"labels": ["规则类型", "类型"], "type": "select",
                          "options": ["max_shifts_per_day", "max_consecutive_days",
                                      "min_rest_hours", "max_weekly_days"]},
            "param_value": {"labels": ["参数值", "值"], "type": "number"},
            "enabled": {"labels": ["启用", "是否启用"], "type": "boolean"},
        },
        "optional_fields": {
            "priority": {"labels": ["优先级"], "type": "number"},
        }
    },
    "schedule": {
        "display_name": "排班结果表",
        "name_keywords": ["排班结果表", "排班表", "schedule", "排班结果"],
        "required_fields": {
            "period": {"labels": ["排班周期", "周期"], "type": "text"},
            "employee": {"labels": ["员工"], "type": "relation"},
            "date": {"labels": ["日期", "排班日期"], "type": "date"},
            "shift": {"labels": ["班次"], "type": "relation"},
        },
        "optional_fields": {
            "status": {"labels": ["状态"], "type": "select",
                       "options": ["待确认", "已确认", "已调整"]},
            "remark": {"labels": ["备注", "说明"], "type": "text"},
        }
    },
    "leave": {
        "display_name": "请假申请表",
        "name_keywords": ["请假申请表", "请假表", "leave", "请假申请", "请假/换班"],
        "required_fields": {
            "applicant": {"labels": ["申请人"], "type": "relation"},
            "leave_type": {"labels": ["申请类型", "类型"], "type": "select",
                           "options": ["请假", "调班"]},
            "leave_date": {"labels": ["请假/换班日期", "请假日期", "换班日期", "日期"], "type": "date"},
            "approval_status": {"labels": ["审批状态", "状态"], "type": "select",
                                "options": ["待审批", "已批准", "已拒绝"]},
        },
        "optional_fields": {
            "reason": {"labels": ["原因", "请假原因", "说明"], "type": "text"},
            "candidates": {"labels": ["候选名单", "候选替班", "候选人"], "type": "subform"},
        }
    }
}


# ============================================================
# 简道云 API 客户端
# ============================================================

class JDYClient:
    def __init__(self, app_id: str, api_key: str):
        self.app_id = app_id
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def get_entries(self) -> List[dict]:
        """获取应用下所有表单"""
        r = httpx.post(f"{BASE_URL}/api/v5/app/entry/list",
                       headers=self.headers,
                       json={"app_id": self.app_id},
                       timeout=30)
        r.raise_for_status()
        return r.json().get("entries", [])

    def get_widgets(self, entry_id: str) -> List[dict]:
        """获取表单所有字段"""
        r = httpx.post(f"{BASE_URL}/api/v5/app/entry/widget/list",
                       headers=self.headers,
                       json={"app_id": self.app_id, "entry_id": entry_id},
                       timeout=30)
        r.raise_for_status()
        return r.json().get("widgets", [])


# ============================================================
# 验证逻辑
# ============================================================

class ValidationResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.details: List[Tuple[str, str, str]] = []  # (status, category, message)

    def ok(self, category: str, msg: str):
        self.passed += 1
        self.details.append(("✅", category, msg))

    def fail(self, category: str, msg: str):
        self.failed += 1
        self.details.append(("❌", category, msg))

    def warn(self, category: str, msg: str):
        self.warnings += 1
        self.details.append(("⚠️", category, msg))

    def print_report(self):
        print()
        print("=" * 60)
        print("  智能排班系统 - 配置验证报告")
        print("=" * 60)
        print()

        current_cat = None
        for status, cat, msg in self.details:
            if cat != current_cat:
                if current_cat:
                    print()
                print(f"【{cat}】")
                current_cat = cat
            print(f"  {status} {msg}")

        print()
        print("-" * 60)
        print(f"  结果: {self.passed} 通过 | {self.failed} 失败 | {self.warnings} 警告")
        print("-" * 60)

        if self.failed == 0:
            print()
            print("  ✅ 配置验证通过！可以运行 init_config.py 生成配置文件。")
        else:
            print()
            print(f"  ❌ 有 {self.failed} 项未通过，请按上方提示修正后重新验证。")
        print()


def match_field(widgets: List[dict], expected_labels: List[str], expected_type: str) -> Tuple[bool, str]:
    """在 widgets 中查找匹配的字段，返回 (是否找到, 匹配到的字段信息)"""
    # 简道云 widget type 映射
    TYPE_MAP = {
        "text": ["text", "serial"],
        "number": ["number"],
        "select": ["select", "radio"],
        "boolean": ["boolean"],
        "date": ["date"],
        "relation": ["link"],
        "subform": ["subform"],
    }
    expected_jdy_types = TYPE_MAP.get(expected_type, [expected_type])

    for w in widgets:
        label = w.get("label", "")
        if label in expected_labels:
            wtype = w.get("type", "")
            if wtype in expected_jdy_types:
                return True, f"'{label}' (type={wtype})"
            else:
                return False, f"'{label}' 类型不匹配: 期望 {expected_type}, 实际 {wtype}"
    return False, f"未找到字段 (期望 label 为 {expected_labels} 之一)"


def validate_table(table_key: str, expected: dict, entries: List[dict],
                   client: JDYClient, result: ValidationResult):
    """验证一张表的结构"""
    display = expected["display_name"]

    # Step 1: 找到表
    matched_entry = None
    for entry in entries:
        entry_name = entry.get("name", "")
        if entry_name in expected["name_keywords"]:
            matched_entry = entry
            break

    if not matched_entry:
        result.fail(display, f"未找到表单 (期望表名包含: {expected['name_keywords']})")
        return

    entry_id = matched_entry["entry_id"]
    result.ok(display, f"找到表单 '{matched_entry['name']}' (entry_id={entry_id})")

    # Step 2: 获取字段
    try:
        widgets = client.get_widgets(entry_id)
    except Exception as e:
        result.fail(display, f"获取字段列表失败: {e}")
        return

    result.ok(display, f"字段数量: {len(widgets)}")

    # Step 3: 验证必填字段
    for field_key, field_def in expected["required_fields"].items():
        found, info = match_field(widgets, field_def["labels"], field_def["type"])
        if found:
            result.ok(display, f"必填字段 [{field_key}] {info}")
        else:
            result.fail(display, f"必填字段 [{field_key}] {info}")

    # Step 4: 验证可选字段
    for field_key, field_def in expected["optional_fields"].items():
        found, info = match_field(widgets, field_def["labels"], field_def["type"])
        if found:
            result.ok(display, f"可选字段 [{field_key}] {info}")
        else:
            result.warn(display, f"可选字段 [{field_key}] {info} (可选，不影响核心功能)")

    # Step 5: 验证单选选项值
    for field_key, field_def in {**expected["required_fields"], **expected["optional_fields"]}.items():
        if field_def["type"] != "select" or "options" not in field_def:
            continue
        for w in widgets:
            if w.get("label") in field_def["labels"] and w.get("type") in ("select", "radio"):
                actual_options = [opt.get("text", opt.get("value", "")) for opt in w.get("options", [])]
                expected_options = field_def["options"]
                missing = [o for o in expected_options if o not in actual_options]
                if not missing:
                    result.ok(display, f"选项值 [{field_key}] 完整: {expected_options}")
                else:
                    result.fail(display,
                                f"选项值 [{field_key}] 缺少: {missing} (实际值: {actual_options})")
                break


# ============================================================
# 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="智能排班系统配置验证")
    parser.add_argument("--app-id", help="简道云应用 ID")
    parser.add_argument("--api-key", help="简道云 API Key")
    parser.add_argument("--config", help="已有的 config.json 路径")
    args = parser.parse_args()

    # 从 config.json 或命令行参数获取凭据
    if args.config:
        with open(args.config, "r") as f:
            config = json.load(f)
        app_id = config["app_id"]
        api_key = config["api_key"]
        print(f"从 {args.config} 读取配置")
    elif args.app_id and args.api_key:
        app_id = args.app_id
        api_key = args.api_key
    else:
        parser.error("需要 --app-id + --api-key，或 --config 参数")
        return

    client = JDYClient(app_id, api_key)
    result = ValidationResult()

    # 获取所有表单
    print(f"正在连接简道云应用 ({app_id})...")
    try:
        entries = client.get_entries()
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("请检查 app_id 和 api_key 是否正确。")
        sys.exit(1)

    print(f"找到 {len(entries)} 个表单，开始逐项验证...")

    # 逐表验证
    found_tables = set()
    for table_key, expected in EXPECTED_TABLES.items():
        validate_table(table_key, expected, entries, client, result)

    # 检查是否有多余的表
    expected_names = set()
    for t in EXPECTED_TABLES.values():
        expected_names.update(t["name_keywords"])
    for entry in entries:
        name = entry.get("name", "")
        if name not in expected_names and not any(kw in name for kw in expected_names):
            result.warn("额外表单", f"'{name}' — 非系统必需，不影响运行")

    # 输出报告
    result.print_report()

    # 退出码
    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()
