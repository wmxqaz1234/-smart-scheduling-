#!/usr/bin/env python3
"""
智能排班系统配置初始化脚本

功能：
1. 连接简道云应用
2. 遍历所有表单（entry）和字段（widget）
3. 通过字段 label 自动识别业务字段
4. 生成 config.json

用法：
    python init_config.py --app-id YOUR_APP_ID --api-key YOUR_API_KEY
"""

import json
import argparse
import sys
from typing import Dict, List, Optional, Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://api.jiandaoyun.com"

# 表名匹配规则（entry name → 业务表 key）
TABLE_NAME_MAPPING = {
    "employee": ["员工信息表", "员工表", "employee"],
    "shift_template": ["班次模板表", "班次表", "shift", "班次"],
    "schedule_rule": ["排班规则表", "规则表", "rule", "排班规则"],
    "schedule": ["排班结果表", "排班表", "schedule", "排班结果"],
    "leave": ["请假申请表", "请假表", "leave", "请假申请", "请假/换班"]
}

# 字段匹配规则（业务字段 key → 可能的 label 列表）
FIELD_LABEL_MAPPING = {
    # employee 表
    "employee.name": ["姓名", "员工姓名", "name"],
    "employee.employee_id": ["工号", "员工工号", "employee_id", "员工编号"],
    "employee.department": ["部门", "所属部门", "department"],
    "employee.position": ["岗位", "职位", "position"],
    "employee.skill_level": ["技能等级", "技能", "skill_level", "技能级别"],
    "employee.max_weekly_days": ["每周最大天数", "最大周天数", "max_weekly_days", "周最大工作天数"],
    "employee.status": ["状态", "员工状态", "status", "在职状态"],
    
    # shift_template 表
    "shift_template.name": ["班次名称", "班次名", "shift_name", "名称"],
    "shift_template.start_time": ["开始时间", "上班时间", "start_time"],
    "shift_template.end_time": ["结束时间", "下班时间", "end_time"],
    "shift_template.duration_hours": ["时长(小时)", "时长", "duration_hours", "小时数"],
    "shift_template.required_count": ["所需人数", "需求人数", "required_count", "人数"],
    "shift_template.shift_type": ["班次类型", "类型", "shift_type"],
    "shift_template.required_skill": ["所需技能", "技能要求", "required_skill"],
    
    # schedule_rule 表
    "schedule_rule.name": ["规则名称", "规则名", "name", "名称"],
    "schedule_rule.rule_type": ["规则类型", "类型", "rule_type"],
    "schedule_rule.param_value": ["参数值", "参数", "param_value", "值"],
    "schedule_rule.priority": ["优先级", "priority"],
    "schedule_rule.enabled": ["启用", "是否启用", "enabled", "状态"],
    
    # schedule 表
    "schedule.period": ["排班周期", "周期", "period", "排班期间"],
    "schedule.employee": ["关联员工", "员工", "employee"],
    "schedule.date": ["日期", "排班日期", "date"],
    "schedule.shift": ["班次", "shift", "关联班次"],
    "schedule.status": ["状态", "排班状态", "status"],
    "schedule.employee_id": ["工号", "员工工号", "employee_id"],
    "schedule.remark": ["备注", "remark", "说明"],
    
    # leave 表
    "leave.employee_id": ["工号", "员工工号", "employee_id", "请假人工号"],
    "leave.applicant": ["申请人", "请假人", "applicant", "申请人姓名"],
    "leave.leave_type": ["申请类型", "请假类型", "leave_type", "类型"],
    "leave.start_date": ["请假/换班日期", "开始日期", "请假开始日期", "start_date", "起始日期"],
    "leave.end_date": ["结束日期", "请假结束日期", "end_date", "截止日期", "换班时间"],
    "leave.reason": ["原因", "请假原因", "reason", "说明"],
    "leave.approval_status": ["部门审批", "审批状态", "状态", "approval_status", "审核状态"],
    "leave.candidates_subform": ["候选名单", "候选员工", "候选人", "candidates"],
    "leave.sub_employee_id": ["工号", "候选工号", "sub_employee_id"],
    "leave.sub_name": ["姓名", "候选姓名", "sub_name"]
}


class ConfigInitializer:
    """配置初始化器"""
    
    def __init__(self, app_id: str, api_key: str):
        self.app_id = app_id
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def _api_request(self, endpoint: str, payload: Dict) -> Dict:
        """发送 API 请求"""
        url = f"{BASE_URL}{endpoint}"
        try:
            response = httpx.post(url, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": True, "status_code": response.status_code, "message": response.text}
        except Exception as e:
            return {"error": True, "message": str(e)}
    
    def list_entries(self) -> List[Dict]:
        """获取应用下所有表单"""
        payload = {
            "app_id": self.app_id,
            "limit": 100
        }
        result = self._api_request("/api/v5/app/entry/list", payload)
        
        if result.get("error"):
            print(f"ERROR: 获取表单列表失败: {result}", file=sys.stderr)
            return []
        
        # API 返回 {"forms": [...]} 格式
        forms = result.get("forms", result.get("data", []))
        return forms
    
    def list_widgets(self, entry_id: str) -> List[Dict]:
        """获取表单的所有字段"""
        payload = {
            "app_id": self.app_id,
            "entry_id": entry_id
        }
        result = self._api_request("/api/v5/app/entry/widget/list", payload)
        
        if result.get("error"):
            print(f"ERROR: 获取字段列表失败 (entry_id={entry_id}): {result}", file=sys.stderr)
            return []
        
        # API 返回 {"widgets": [...]} 格式
        return result.get("widgets", result.get("data", []))
    
    def match_table_name(self, entry_name: str) -> Optional[str]:
        """通过 entry name 匹配业务表"""
        entry_name_lower = entry_name.lower()
        for table_key, possible_names in TABLE_NAME_MAPPING.items():
            for name in possible_names:
                if name.lower() in entry_name_lower or entry_name_lower in name.lower():
                    return table_key
        return None
    
    def match_field_label(self, table_key: str, widget_label: str) -> Optional[str]:
        """通过 widget label 匹配业务字段（精确匹配优先）"""
        widget_label_stripped = widget_label.strip()
        prefix = f"{table_key}."
        
        # 第一轮：精确匹配
        for field_key, possible_labels in FIELD_LABEL_MAPPING.items():
            if not field_key.startswith(prefix):
                continue
            for label in possible_labels:
                if widget_label_stripped == label:
                    return field_key.split(".")[-1]
        
        # 第二轮：包含匹配（widget label 包含候选 label）
        for field_key, possible_labels in FIELD_LABEL_MAPPING.items():
            if not field_key.startswith(prefix):
                continue
            for label in possible_labels:
                if label in widget_label_stripped:
                    return field_key.split(".")[-1]
        
        return None
    
    def match_fields_for_table(self, table_key: str, widgets: List[Dict]) -> Dict[str, str]:
        """为指定表匹配所有字段，确保每个 widget 只被匹配一次。
        sub_ 前缀的字段（子表单字段）不在此处匹配，由子表单提取逻辑处理。"""
        matched = {}  # field_key → widget_name
        used_widgets = set()  # 已使用的 widget_name
        
        prefix = f"{table_key}."
        field_entries = [
            (k, v) for k, v in FIELD_LABEL_MAPPING.items()
            if k.startswith(prefix) and not k.split(".")[-1].startswith("sub_")
        ]
        
        # 第一轮：精确匹配
        for field_key, possible_labels in field_entries:
            short_key = field_key.split(".")[-1]
            if short_key in matched:
                continue
            for widget in widgets:
                w_name = widget.get("name", "")
                w_label = widget.get("label", "").strip()
                if w_name in used_widgets:
                    continue
                for label in possible_labels:
                    if w_label == label:
                        matched[short_key] = w_name
                        used_widgets.add(w_name)
                        break
                if short_key in matched:
                    break
        
        # 第二轮：包含匹配（仅对未匹配的字段）
        for field_key, possible_labels in field_entries:
            short_key = field_key.split(".")[-1]
            if short_key in matched:
                continue
            for widget in widgets:
                w_name = widget.get("name", "")
                w_label = widget.get("label", "").strip()
                if w_name in used_widgets:
                    continue
                for label in possible_labels:
                    if label in w_label:
                        matched[short_key] = w_name
                        used_widgets.add(w_name)
                        break
                if short_key in matched:
                    break
        
        return matched
    
    def build_config(self) -> Dict:
        """构建配置"""
        print(f"正在连接应用 {self.app_id}...")
        
        entries = self.list_entries()
        if not entries:
            print("ERROR: 未找到任何表单", file=sys.stderr)
            return {}
        
        print(f"找到 {len(entries)} 个表单")
        
        config = {
            "_comment": "智能排班系统配置 - 自动生成",
            "app_id": self.app_id,
            "api_key": self.api_key,
            "tables": {}
        }
        
        # 匹配业务表
        for entry in entries:
            entry_id = entry.get("entry_id", entry.get("_id", ""))
            entry_name = entry.get("name", "")
            
            table_key = self.match_table_name(entry_name)
            if not table_key:
                print(f"  跳过未识别的表单: {entry_name}")
                continue
            
            print(f"  识别表单: {entry_name} → {table_key}")
            
            # 获取字段
            widgets = self.list_widgets(entry_id)
            if not widgets:
                print(f"    WARNING: 表单 {entry_name} 无字段")
                continue
            
            # 匹配字段（精确匹配优先，每个 widget 只匹配一次）
            fields = self.match_fields_for_table(table_key, widgets)
            for field_key, widget_name in sorted(fields.items()):
                # 找到对应的 label 用于显示
                label = ""
                for w in widgets:
                    if w.get("name") == widget_name:
                        label = w.get("label", "")
                        break
                print(f"    识别字段: {label} → {field_key} ({widget_name})")
            
            # 特殊处理：从子表单的 items 数组提取子字段
            for widget in widgets:
                if widget.get("type") != "subform":
                    continue
                
                sf_name = widget.get("name", "")
                sf_label = widget.get("label", "")
                
                # 记录子表单 widget_id
                if "candidates_subform" not in fields:
                    fields["candidates_subform"] = sf_name
                    print(f"    识别子表单: {sf_label} → candidates_subform ({sf_name})")
                
                # 子字段直接在 items 数组中
                for sub_w in widget.get("items", []):
                    sub_name = sub_w.get("name", "")
                    sub_label = sub_w.get("label", "").strip()
                    
                    if sub_label == "工号" and "sub_employee_id" not in fields:
                        fields["sub_employee_id"] = sub_name
                        print(f"    识别子表单字段: {sub_label} → sub_employee_id ({sub_name})")
                    
                    if sub_label == "姓名" and "sub_name" not in fields:
                        fields["sub_name"] = sub_name
                        print(f"    识别子表单字段: {sub_label} → sub_name ({sub_name})")
            
            config["tables"][table_key] = {
                "entry_id": entry_id,
                "fields": fields
            }
        
        # 生成 webhook_payload_fields（payload 字段映射）
        if "leave" in config["tables"]:
            leave_fields = config["tables"]["leave"]["fields"]
            config["webhook_payload_fields"] = {
                "employee_id": leave_fields.get("employee_id", ""),
                "applicant": leave_fields.get("applicant", ""),
                "leave_date": leave_fields.get("start_date", "")
            }
        
        return config
    
    def validate_config(self, config: Dict) -> bool:
        """验证配置完整性"""
        required_tables = ["employee", "shift_template", "schedule_rule", "schedule", "leave"]
        missing_tables = [t for t in required_tables if t not in config.get("tables", {})]
        
        if missing_tables:
            print(f"\nWARNING: 缺少必要的表: {', '.join(missing_tables)}", file=sys.stderr)
            return False
        
        # 检查关键字段
        required_fields = {
            "employee": ["name", "employee_id", "status"],
            "shift_template": ["name", "required_count"],
            "schedule": ["date", "employee_id", "status"],
            "leave": ["employee_id", "start_date", "candidates_subform"]
        }
        
        for table_key, fields in required_fields.items():
            table_config = config["tables"].get(table_key, {})
            table_fields = table_config.get("fields", {})
            missing = [f for f in fields if f not in table_fields]
            
            if missing:
                print(f"\nWARNING: {table_key} 表缺少字段: {', '.join(missing)}", file=sys.stderr)
        
        return True


def main():
    parser = argparse.ArgumentParser(
        description="智能排班系统配置初始化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python init_config.py --app-id YOUR_APP_ID --api-key YOUR_API_KEY
        """
    )
    
    parser.add_argument("--app-id", required=True, help="简道云应用 ID")
    parser.add_argument("--api-key", required=True, help="简道云 API Key")
    
    parser.add_argument("--output", default="skills/smart-scheduling/config.json", help="输出配置文件路径")
    
    args = parser.parse_args()
    
    api_key = args.api_key
    
    # 初始化
    initializer = ConfigInitializer(args.app_id, api_key)
    config = initializer.build_config()
    
    if not config:
        print("ERROR: 配置生成失败", file=sys.stderr)
        sys.exit(1)
    
    # 验证
    print("\n验证配置...")
    is_valid = initializer.validate_config(config)
    
    if not is_valid:
        print("WARNING: 配置不完整，但仍可保存", file=sys.stderr)
    
    # 保存
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"\n配置已保存到: {args.output}")
    
    # 输出摘要
    print("\n配置摘要:")
    for table_key, table_config in config.get("tables", {}).items():
        entry_id = table_config.get("entry_id", "")
        fields_count = len(table_config.get("fields", {}))
        print(f"  {table_key}: entry_id={entry_id}, fields={fields_count}")
    
    if "webhook_payload_fields" in config:
        print("\nWebhook Payload 字段映射:")
        for key, value in config["webhook_payload_fields"].items():
            print(f"  {key}: {value}")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
