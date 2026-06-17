#!/usr/bin/env python3
"""
请假候选员工查询脚本

功能：
1. 读取排班系统配置
2. 从简道云查询在职员工
3. 查询请假日期范围内已排班的员工
4. 筛选可用候选员工（排除已排班 + 请假者本人）
5. 将候选名单写回请假表的子表单

用法：
    # 从命令行参数传入 payload JSON
    python leave_candidates.py --payload '{"employee_id": "E010", "start_date": "2026-06-19T16:00:00.000Z"}'
    
    # 从文件读取 payload
    python leave_candidates.py --payload-file payload.json
    
    # 指定配置文件路径
    python leave_candidates.py --payload '...' --config skills/smart-scheduling/config.json
"""

import json
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# 添加脚本目录到路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)

from tz_util import utc_to_bj_date, bj_date_to_utc_midnight, bj_date_to_utc_range


BASE_URL = "https://api.jiandaoyun.com"
DEFAULT_CONFIG_PATH = "skills/smart-scheduling/config.json"


class LeaveCandidateQuery:
    """请假候选员工查询器"""
    
    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        """初始化，加载配置"""
        self.config_path = config_path
        self._load_config()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def _load_config(self):
        """加载配置文件"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        
        self.app_id = cfg["app_id"]
        self.emp_table = cfg["tables"]["employee"]
        self.sch_table = cfg["tables"]["schedule"]
        self.lve_table = cfg["tables"]["leave"]
        self.shift_template_table = cfg["tables"]["shift_template"]
        
        # API Key: 直接从 config.json 读取
        self.api_key = cfg.get("api_key", "")
        if not self.api_key:
            raise ValueError("API Key not found in config. Please run init_config.py first or set api_key in config.json")
        
        # Webhook payload 字段映射（标准名 → 实际 widget_id）
        self.webhook_payload_fields = cfg.get("webhook_payload_fields", {})
        
        # 请假表字段映射
        self.leave_fields = cfg["tables"]["leave"]["fields"]
        
        # 排班规则表配置
        self.rule_table = cfg.get("tables", {}).get("schedule_rule")
        
        # 技能等级映射
        self.skill_level_map = {"初级": 1, "中级": 2, "高级": 3}
        
        # 默认排班规则值
        self.default_rules = {
            "max_weekly_days": 5,
            "max_consecutive_days": 6,
            "min_rest_hours": None,
            "max_shifts_per_day": 1
        }
    
    def _api_request(self, endpoint: str, payload: Dict, method: str = "POST", retries: int = 1) -> Dict:
        """发送 API 请求，支持重试"""
        url = f"{BASE_URL}{endpoint}"
        
        for attempt in range(retries + 1):
            try:
                response = httpx.post(url, json=payload, headers=self.headers, timeout=30)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429 and attempt < retries:
                    # 限流，等待后重试
                    import time
                    time.sleep(2 ** attempt)
                    continue
                else:
                    return {
                        "error": True,
                        "status_code": response.status_code,
                        "message": response.text
                    }
            except Exception as e:
                if attempt < retries:
                    import time
                    time.sleep(1)
                    continue
                return {"error": True, "message": str(e)}
        
        return {"error": True, "message": "Max retries exceeded"}
    
    def query_schedule_rules(self) -> Dict:
        """查询启用的排班规则"""
        if not self.rule_table:
            return self.default_rules
        
        fields = self.rule_table["fields"]
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.rule_table["entry_id"],
            "fields": [fields["rule_type"], fields["param_value"], fields["enabled"]],
            "filter": {
                "rel": "and",
                "cond": [{
                    "field": fields["enabled"],
                    "type": "bool",
                    "method": "eq",
                    "value": True
                }]
            },
            "limit": 100
        }
        
        result = self._api_request("/api/v5/app/entry/data/list", payload)
        
        if result.get("error"):
            return self.default_rules
        
        rules = dict(self.default_rules)
        for item in result.get("data", []):
            rule_type = item.get(fields["rule_type"], "")
            param_value = item.get(fields["param_value"], 0)
            
            if rule_type == "max_weekly_days":
                rules["max_weekly_days"] = int(param_value)
            elif rule_type == "max_consecutive_days":
                rules["max_consecutive_days"] = int(param_value)
            elif rule_type == "min_rest_hours":
                rules["min_rest_hours"] = int(param_value)
            elif rule_type == "max_shifts_per_day":
                rules["max_shifts_per_day"] = int(param_value)
        
        return rules
    
    def query_employee_schedule_detail(self, employee_id: str, center_date_utc: str, days_range: int = 1) -> List[Dict]:
        """
        查询员工在指定日期范围内的排班明细
        
        Args:
            employee_id: 员工工号
            center_date_utc: 中心日期（UTC 格式）
            days_range: 前后天数范围（默认 1，即查询前1天、当天、后1天共3天）
        
        Returns:
            [
                {"date": "2026-06-23", "shift_name": "早班", "status": "已排班"},
                {"date": "2026-06-24", "shift_name": "", "status": "未排班"},
                ...
            ]
        """
        from datetime import datetime, timedelta
        
        bj_date = utc_to_bj_date(center_date_utc)
        d = datetime.strptime(bj_date, "%Y-%m-%d")
        
        # 计算日期范围
        start_date = d - timedelta(days=days_range)
        end_date = d + timedelta(days=days_range)
        
        start_bj = start_date.strftime("%Y-%m-%d")
        end_bj = end_date.strftime("%Y-%m-%d")
        
        # 转换为 UTC 零点格式
        start_utc = bj_date_to_utc_midnight(start_bj)
        end_utc = bj_date_to_utc_midnight(end_bj)
        
        fields = self.sch_table["fields"]
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.sch_table["entry_id"],
            "fields": [fields["date"], fields["shift_name"], fields["status"]],
            "filter": {
                "rel": "and",
                "cond": [
                    {
                        "field": fields["date"],
                        "type": "datetime",
                        "method": "range",
                        "value": [start_utc, end_utc]
                    },
                    {
                        "field": fields["employee_id"],
                        "type": "text",
                        "method": "eq",
                        "value": [employee_id]
                    }
                ]
            },
            "limit": 100
        }
        
        result = self._api_request("/api/v5/app/entry/data/list", payload)
        
        # 构建日期到排班信息的映射
        schedule_map = {}
        if not result.get("error"):
            for item in result.get("data", []):
                date_val = item.get(fields["date"], "")
                if date_val:
                    sched_bj_date = utc_to_bj_date(date_val)
                    schedule_map[sched_bj_date] = {
                        "date": sched_bj_date,
                        "shift_name": item.get(fields["shift_name"], ""),
                        "status": item.get(fields["status"], "已排班") or "已排班"
                    }
        
        # 生成完整的日期列表（包含未排班的日期）
        schedule_details = []
        current = start_date
        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            if date_str in schedule_map:
                schedule_details.append(schedule_map[date_str])
            else:
                schedule_details.append({
                    "date": date_str,
                    "shift_name": "",
                    "status": "未排班"
                })
            current += timedelta(days=1)
        
        return schedule_details
    
    def query_employee_schedule_count(self, employee_id: str, date_utc: str) -> Dict:
        """
        查询员工在指定日期所在周的排班情况
        
        Returns:
            {
                "week_dates": ["2026-06-22", "2026-06-23", ...],  # 本周所有日期
                "scheduled_dates": ["2026-06-23", "2026-06-25"],  # 已排班日期
                "week_count": 2,  # 本周已排班天数
                "consecutive_before": 1,  # 向前连续工作天数
                "consecutive_after": 0   # 向后连续工作天数
            }
        """
        from datetime import datetime, timedelta
        
        # 转换为北京时间日期
        bj_date = utc_to_bj_date(date_utc)
        d = datetime.strptime(bj_date, "%Y-%m-%d")
        
        # 计算本周范围（周一到周日）
        week_start = d - timedelta(days=d.weekday())
        week_dates = [(week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        
        # 查询本周该员工的排班记录
        fields = self.sch_table["fields"]
        
        # 构建日期范围过滤（UTC 格式）
        start_utc = bj_date_to_utc_midnight(week_dates[0])
        end_utc = bj_date_to_utc_midnight(week_dates[-1])
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.sch_table["entry_id"],
            "fields": [fields["date"], fields["employee_id"]],
            "filter": {
                "rel": "and",
                "cond": [
                    {
                        "field": fields["date"],
                        "type": "datetime",
                        "method": "range",
                        "value": [start_utc, end_utc]
                    },
                    {
                        "field": fields["employee_id"],
                        "type": "text",
                        "method": "eq",
                        "value": [employee_id]
                    }
                ]
            },
            "limit": 100
        }
        
        result = self._api_request("/api/v5/app/entry/data/list", payload)
        
        scheduled_dates = set()
        if not result.get("error"):
            for item in result.get("data", []):
                date_val = item.get(fields["date"], "")
                if date_val:
                    # 转换为北京时间日期
                    sched_bj_date = utc_to_bj_date(date_val)
                    scheduled_dates.add(sched_bj_date)
        
        # 计算连续工作天数
        consecutive_before = 0
        cur = d - timedelta(days=1)
        while cur.strftime("%Y-%m-%d") in scheduled_dates:
            consecutive_before += 1
            cur -= timedelta(days=1)
        
        consecutive_after = 0
        cur = d + timedelta(days=1)
        while cur.strftime("%Y-%m-%d") in scheduled_dates:
            consecutive_after += 1
            cur += timedelta(days=1)
        
        return {
            "week_dates": week_dates,
            "scheduled_dates": sorted(list(scheduled_dates)),
            "week_count": len(scheduled_dates),
            "consecutive_before": consecutive_before,
            "consecutive_after": consecutive_after
        }
    
    def check_schedule_rules(self, employee_id: str, target_date_utc: str, rules: Dict) -> Dict:
        """
        检查员工在目标日期顶替班次是否违反排班规则
        
        Returns:
            {"valid": True/False, "reason": "违规原因或空字符串"}
        """
        schedule_info = self.query_employee_schedule_count(employee_id, target_date_utc)
        
        # 检查每周工作天数
        max_weekly = rules.get("max_weekly_days", 5)
        # 如果目标日期不在已排班日期中，需要 +1
        target_bj_date = utc_to_bj_date(target_date_utc)
        new_week_count = schedule_info["week_count"]
        if target_bj_date not in schedule_info["scheduled_dates"]:
            new_week_count += 1
        
        if new_week_count > max_weekly:
            return {
                "valid": False,
                "reason": f"每周工作天数超限（当前{schedule_info['week_count']}天，顶替后{new_week_count}天，上限{max_weekly}天）"
            }
        
        # 检查连续工作天数
        max_consecutive = rules.get("max_consecutive_days", 6)
        # 计算包含目标日期的连续天数
        consecutive_total = schedule_info["consecutive_before"] + 1 + schedule_info["consecutive_after"]
        
        if consecutive_total > max_consecutive:
            return {
                "valid": False,
                "reason": f"连续工作天数超限（连续{consecutive_total}天，上限{max_consecutive}天）"
            }
        
        return {"valid": True, "reason": ""}
    
    def query_active_employees(self) -> List[Dict]:
        """查询在职员工列表（包含技能等级）"""
        fields = self.emp_table["fields"]
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.emp_table["entry_id"],
            "fields": [fields["name"], fields["employee_id"], fields["status"], fields["skill_level"]],
            "filter": {
                "rel": "and",
                "cond": [{
                    "field": fields["status"],
                    "type": "text",
                    "method": "eq",
                    "value": ["在职"]
                }]
            },
            "limit": 1000
        }
        
        result = self._api_request("/api/v5/app/entry/data/list", payload)
        
        if result.get("error"):
            return []
        
        employees = []
        for item in result.get("data", []):
            employees.append({
                "name": item.get(fields["name"], ""),
                "employee_id": item.get(fields["employee_id"], ""),
                "status": item.get(fields["status"], ""),
                "skill_level": item.get(fields["skill_level"], "初级")
            })
        
        return employees
    
    def _normalize_date_to_utc_midnight(self, date_utc: str) -> str:
        """
        将日期转换为 UTC 零点格式（排班表存储格式）
        
        排班表存储格式: 2026-06-16T00:00:00.000Z (UTC 零点)
        Webhook 传入格式: 2026-06-15T16:00:00.000Z (北京时间 6月16日 00:00)
        
        转换逻辑: UTC 时间 → 北京时间日期 → UTC 零点格式
        """
        try:
            bj_date = utc_to_bj_date(date_utc)
            return bj_date_to_utc_midnight(bj_date)
        except Exception:
            return date_utc
    
    def query_scheduled_employees(self, start_date_utc: str, end_date_utc: str) -> List[str]:
        """查询指定日期范围内已排班的员工工号列表"""
        fields = self.sch_table["fields"]
        
        # 如果结束日期为空，使用开始日期
        if not end_date_utc:
            end_date_utc = start_date_utc
        
        # 转换为排班表的存储格式（UTC 零点）
        start_normalized = self._normalize_date_to_utc_midnight(start_date_utc)
        end_normalized = self._normalize_date_to_utc_midnight(end_date_utc)
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.sch_table["entry_id"],
            "fields": [fields["employee_id"]],
            "filter": {
                "rel": "and",
                "cond": [
                    {
                        "field": fields["date"],
                        "type": "datetime",
                        "method": "range",
                        "value": [start_normalized, end_normalized]
                    }
                ]
            },
            "limit": 1000
        }
        
        result = self._api_request("/api/v5/app/entry/data/list", payload)
        
        if result.get("error"):
            return []
        
        scheduled_ids = set()
        for item in result.get("data", []):
            emp_id = item.get(fields["employee_id"], "")
            if emp_id:
                scheduled_ids.add(emp_id)
        
        return list(scheduled_ids)
    
    def query_leave_shift_info(self, employee_id: str, date_utc: str, data_id: Optional[str] = None) -> Optional[Dict]:
        """
        查询请假人的班次信息（优先从请假记录中读取班次名称，再查班次模板获取技能要求）
        
        Returns:
            {"shift_name": "...", "required_skill": "..."} 或 None
        """
        fields = self.lve_table["fields"]
        shift_fields = self.shift_template_table["fields"]
        
        # 优先使用 data_id 直接获取请假记录中的班次名称
        shift_name = None
        if data_id:
            payload = {
                "app_id": self.app_id,
                "entry_id": self.lve_table["entry_id"],
                "data_id": data_id
            }
            result = self._api_request("/api/v5/app/entry/data/get", payload)
            
            if not result.get("error") and result.get("data"):
                leave_data = result["data"]
                shift_name = leave_data.get(fields.get("shift_name", ""), "")
        
        # 如果没有 data_id 或请假记录中没有班次名称，尝试从排班表查询
        if not shift_name:
            sch_fields = self.sch_table["fields"]
            
            # 转换为排班表的存储格式（UTC 零点）
            date_normalized = self._normalize_date_to_utc_midnight(date_utc)
            
            # 查询请假人当天的排班记录
            payload = {
                "app_id": self.app_id,
                "entry_id": self.sch_table["entry_id"],
                "fields": [sch_fields["employee_id"], sch_fields["shift"], sch_fields["shift_name"]],
                "filter": {
                    "rel": "and",
                    "cond": [
                        {
                            "field": sch_fields["date"],
                            "type": "datetime",
                            "method": "eq",
                            "value": date_normalized
                        },
                        {
                            "field": sch_fields["employee_id"],
                            "type": "text",
                            "method": "eq",
                            "value": [employee_id]
                        }
                    ]
                },
                "limit": 10
            }
            
            result = self._api_request("/api/v5/app/entry/data/list", payload)
            
            if result.get("error") or not result.get("data"):
                return None
            
            schedule_item = result["data"][0]
            shift_name = schedule_item.get(sch_fields["shift_name"], "")
        
        if not shift_name:
            return None
        
        # 根据班次名称查询班次模板的技能要求
        shift_payload = {
            "app_id": self.app_id,
            "entry_id": self.shift_template_table["entry_id"],
            "fields": [shift_fields["name"], shift_fields["required_skill"]],
            "filter": {
                "rel": "and",
                "cond": [{
                    "field": shift_fields["name"],
                    "type": "text",
                    "method": "eq",
                    "value": [shift_name]
                }]
            },
            "limit": 1
        }
        
        shift_result = self._api_request("/api/v5/app/entry/data/list", shift_payload)
        
        if shift_result.get("error") or not shift_result.get("data"):
            return {
                "shift_name": shift_name,
                "required_skill": "无"
            }
        
        shift_template = shift_result["data"][0]
        required_skill = shift_template.get(shift_fields["required_skill"], "无")
        
        return {
            "shift_name": shift_name,
            "required_skill": required_skill if required_skill else "无"
        }
    
    def check_skill_match(self, employee_skill_level: str, required_skill: str) -> bool:
        """
        检查员工技能是否满足班次要求
        
        Args:
            employee_skill_level: 员工技能等级（初级/中级/高级）
            required_skill: 班次要求的技能等级
        
        Returns:
            True 如果员工技能 >= 要求技能（严格匹配，不降级）
        """
        if not required_skill or required_skill == "无":
            return True
        
        emp_val = self.skill_level_map.get(employee_skill_level, 1)
        req_val = self.skill_level_map.get(required_skill, 1)
        
        # 严格匹配：员工技能必须 >= 要求技能
        return emp_val >= req_val
    
    def get_leave_data_id(self, employee_id: str, leave_date_utc: str = "", data_id: Optional[str] = None) -> Optional[str]:
        """获取请假记录的 data_id，根据员工工号和请假日期精确匹配"""
        if data_id:
            return data_id
        
        fields = self.lve_table["fields"]
        
        # 构建过滤条件：工号匹配
        conditions = [{
            "field": fields["employee_id"],
            "type": "text",
            "method": "eq",
            "value": [employee_id]
        }]
        
        # 如果有请假日期，增加日期过滤条件
        if leave_date_utc:
            # 转换为北京时间日期，再生成 UTC 查询范围
            bj_date = utc_to_bj_date(leave_date_utc)
            start_utc, end_utc = bj_date_to_utc_range(bj_date)
            
            conditions.append({
                "field": fields["start_date"],
                "type": "datetime",
                "method": "range",
                "value": [start_utc, end_utc]
            })
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.lve_table["entry_id"],
            "fields": [fields["employee_id"], fields["start_date"]],
            "filter": {
                "rel": "and",
                "cond": conditions
            },
            "order_by": [{"field": "_created_at", "type": "desc"}],
            "limit": 1
        }
        
        result = self._api_request("/api/v5/app/entry/data/list", payload)
        
        if result.get("error"):
            return None
        
        data_list = result.get("data", [])
        if data_list:
            return data_list[0].get("_id", "")
        
        return None
    
    def check_subform_has_data(self, data_id: str) -> bool:
        """检查请假记录的候选子表单是否已有数据
        
        Args:
            data_id: 请假记录的数据ID
            
        Returns:
            True 如果子表单已有数据（非空），False 如果为空或查询失败
        """
        if not data_id:
            return False
        
        fields = self.lve_table["fields"]
        subform_field = fields["candidates_subform"]
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.lve_table["entry_id"],
            "data_id": data_id
        }
        
        result = self._api_request("/api/v5/app/entry/data/get", payload)
        
        if result.get("error") or not result.get("data"):
            return False
        
        existing_subform = result["data"].get(subform_field, [])
        
        return bool(existing_subform)
    
    def update_candidates_subform(self, data_id: str, candidates: List[Dict], leave_date_utc: str = "", shift_name: str = "") -> Dict:
        """更新请假表的候选子表单
        
        写入前先检查子表单是否已有数据，已有数据则跳过写入。
        
        子表单每行展示：
        - 日期：换班日期
        - 班次：候选人自己今天和明天的排班班次（可能多条，如"早班、中班"）
        - 工号/姓名：候选人信息
        
        Returns:
            {"updated": bool, "skipped": bool, "reason": str}
            - updated=True: 写入成功
            - skipped=True: 子表单已有数据，跳过写入
            - 两者皆 False: 写入失败
        """
        if not data_id:
            return {"updated": False, "skipped": False, "reason": "无 data_id"}
        
        fields = self.lve_table["fields"]
        
        # 预检查：子表单是否已有数据
        if self.check_subform_has_data(data_id):
            return {"updated": False, "skipped": True, "reason": "子表单已有数据，跳过写入"}
        
        # 构建子表单数据
        subform_rows = []
        for emp in candidates:
            # 查询候选人今天和明天的排班（换班日期 + 后1天）
            schedule_details = self.query_employee_schedule_detail(emp["employee_id"], leave_date_utc, days_range=1) if leave_date_utc else []
            
            # 日期：换班日期
            date_for_subform = ""
            if leave_date_utc:
                try:
                    bj_date = utc_to_bj_date(leave_date_utc)
                    date_for_subform = bj_date_to_utc_midnight(bj_date)
                except Exception:
                    date_for_subform = leave_date_utc
            
            # 班次：候选人自己今天和明天的排班班次
            # schedule_details 包含 [换班日期(今天), 明天]，取每条的班次名
            candidate_shifts = []
            if schedule_details:
                for detail in schedule_details:
                    shift = detail.get("shift_name", "")
                    if shift:
                        candidate_shifts.append(shift)
                    else:
                        candidate_shifts.append("休息")
            candidate_shift_str = "、".join(candidate_shifts) if candidate_shifts else "休息"
            
            row = {
                fields.get("sub_datetime", "_widget_1781598769478"): {"value": date_for_subform},
                fields.get("sub_shift", "_widget_1781598769479"): {"value": candidate_shift_str},
                fields["sub_employee_id"]: {"value": emp["employee_id"]},
                fields["sub_name"]: {"value": emp["name"]}
            }
            
            subform_rows.append(row)
        
        subform_data = {"value": subform_rows}
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.lve_table["entry_id"],
            "data_id": data_id,
            "data": {
                fields["candidates_subform"]: subform_data
            }
        }
        
        result = self._api_request("/api/v5/app/entry/data/update", payload)
        
        if result.get("error"):
            return {"updated": False, "skipped": False, "reason": f"API 写入失败: {result.get('message', '未知错误')}"}
        
        return {"updated": True, "skipped": False, "reason": "写入成功"}
    
    def run(self, payload: Dict) -> Dict:
        """
        执行完整的候选员工查询流程（自动识别请假/调班场景）
        
        Args:
            payload: Webhook 传入的数据，包含：
                - employee_id: 请假/调班员工工号
                - applicant: 申请人姓名（可选）
                - leave_date: 请假/换班日期（UTC 格式，单日期字段）
                - leave_type: 申请类型（请假/调班，可选）
                - data_id: 记录的 _id（可选，优先使用）
        
        Returns:
            结构化结果字典
        """
        # 解析 payload — 使用 config 中的字段映射
        # webhook_payload_fields 映射标准名 → 实际字段名
        # 如 {"employee_id": "gonghao"}，则从 payload["gonghao"] 取值
        # 如果映射不存在，直接用标准名（兼容测试场景）
        m = self.webhook_payload_fields
        leave_employee_id = payload.get(m.get("employee_id", "employee_id"), "") or payload.get("employee_id", "")
        applicant = payload.get(m.get("applicant", "applicant"), "") or payload.get("applicant", "")
        leave_date_utc = payload.get(m.get("leave_date", "leave_date"), "") or payload.get("leave_date", "") or payload.get("start_date", "")
        
        # 解析申请类型（请假/调班）
        leave_type_field = self.leave_fields.get("leave_type", "leave_type")
        leave_type = payload.get(leave_type_field, "") or payload.get("leave_type", "") or payload.get("type", "")
        
        # 自动判定场景类型
        if leave_type in ["调班", "换班", "swap", "exchange"]:
            scenario_type = "shift_swap"
            scenario_label = "调班"
        else:
            scenario_type = "leave"
            scenario_label = "请假"
        
        # 优先使用 payload 中的 data_id（简道云 Webhook 推送的字段名可能是 dataid、_id 或 data_id）
        payload_data_id = payload.get("dataid", "") or payload.get("_id", "") or payload.get("data_id", "")
        
        # 单日期字段：开始和结束日期相同
        start_date_utc = leave_date_utc
        end_date_utc = leave_date_utc
        
        # 验证必填字段
        if not leave_employee_id:
            return {
                "success": False,
                "error": "缺少请假员工工号 (employee_id/gonghao)",
                "payload": payload
            }
        
        if not leave_date_utc:
            return {
                "success": False,
                "error": "缺少请假/换班日期 (leave_date/shijian)",
                "payload": payload
            }
        
        # 转换日期显示（UTC → 北京时间日期）
        start_display = utc_to_bj_date(start_date_utc)
        
        # Step 1: 查询在职员工
        employees = self.query_active_employees()
        if not employees:
            return {
                "success": False,
                "error": "查询在职员工失败或无在职员工"
            }
        
        # Step 2: 查询请假人当天的班次及技能要求（优先从请假记录中读取）
        shift_info = self.query_leave_shift_info(leave_employee_id, start_date_utc, payload_data_id if payload_data_id else None)
        required_skill = shift_info.get("required_skill", "无") if shift_info else "无"
        
        # Step 3: 查询已排班员工
        scheduled_ids = self.query_scheduled_employees(start_date_utc, end_date_utc)
        
        # Step 3.5: 查询排班规则
        rules = self.query_schedule_rules()
        
        # Step 4: 筛选候选名单
        # 候选人 = 当天没有排班的非本人员工（有空来替班）
        # 子表单中展示申请人的班次（候选人需要替的班）+ 候选人自己的近几天排班明细
        scheduled_set = set(scheduled_ids)
        candidates = []
        rejected_by_rules = []  # 记录因规则被排除的员工
        
        for emp in employees:
            # 排除请假者本人
            if emp["employee_id"] == leave_employee_id:
                continue
            
            # 排除当天已排班的员工（他们已经上班了，不能再替班）
            if emp["employee_id"] in scheduled_set:
                continue
            
            # 检查技能匹配
            if not self.check_skill_match(emp.get("skill_level", "初级"), required_skill):
                continue
            
            # 检查排班规则
            rule_check = self.check_schedule_rules(emp["employee_id"], start_date_utc, rules)
            if not rule_check["valid"]:
                rejected_by_rules.append({
                    "employee_id": emp["employee_id"],
                    "name": emp["name"],
                    "reason": rule_check["reason"]
                })
                continue
            
            candidates.append(emp)
        
        # Step 5: 获取 data_id（优先使用 payload 中的 _id，否则通过工号+日期精确匹配）
        final_data_id = self.get_leave_data_id(leave_employee_id, leave_date_utc, payload_data_id if payload_data_id else None)
        
        # Step 6: 为每个候选人查询排班明细（请假当天及前后各1天，共3天）
        candidates_with_schedule = []
        for emp in candidates:
            schedule_details = self.query_employee_schedule_detail(emp["employee_id"], start_date_utc, days_range=1)
            
            # 提取候选人当天的班次
            candidate_shift_today = ""
            if schedule_details:
                # 找到当天的排班（schedule_details 是按日期排序的，中间那个是当天）
                today_idx = 1 if len(schedule_details) >= 2 else 0
                today_schedule = schedule_details[today_idx] if len(schedule_details) > today_idx else {}
                candidate_shift_today = today_schedule.get("shift_name", "")
            
            # 格式化排班明细字符串
            schedule_summary_parts = []
            for detail in schedule_details:
                date_str = detail["date"]
                shift = detail.get("shift_name", "")
                if shift:
                    schedule_summary_parts.append(f"{date_str}:{shift}")
                else:
                    schedule_summary_parts.append(f"{date_str}:休息")
            schedule_summary = "; ".join(schedule_summary_parts)
            
            candidates_with_schedule.append({
                **emp,
                "shift_on_leave_date": candidate_shift_today,
                "schedule_detail": schedule_summary,
                "schedule_days": schedule_details
            })
        
        # Step 7: 更新子表单（dry-run 模式跳过写入；子表单已有数据也跳过）
        dry_run = payload.get("_dry_run", False)
        update_success = False
        subform_skipped = False
        subform_skip_reason = ""
        if candidates and final_data_id and not dry_run:
            # 获取班次名称用于填充子表单
            shift_name_for_subform = shift_info.get("shift_name", "") if shift_info else ""
            update_result = self.update_candidates_subform(
                final_data_id, 
                candidates, 
                leave_date_utc=start_date_utc,
                shift_name=shift_name_for_subform
            )
            update_success = update_result.get("updated", False)
            subform_skipped = update_result.get("skipped", False)
            subform_skip_reason = update_result.get("reason", "")
        
        # 构建结果
        result = {
            "success": True,
            "scenario_type": scenario_type,
            "scenario_label": scenario_label,
            "leave_type": leave_type if leave_type else "请假",
            "leave_info": {
                "employee_id": leave_employee_id,
                "applicant": applicant,
                "leave_date_utc": leave_date_utc,
                "leave_date_display": start_display,
                "data_id": final_data_id,
                "shift_info": shift_info
            },
            "skill_requirement": {
                "required_skill": required_skill,
                "skill_level_map": self.skill_level_map
            },
            "statistics": {
                "total_employees": len(employees),
                "scheduled_count": len(scheduled_ids),
                "candidates_count": len(candidates),
                "rejected_by_rules_count": len(rejected_by_rules)
            },
            "schedule_rules": rules,
            "rejected_by_rules": rejected_by_rules,
            "scheduled_ids": sorted(scheduled_ids),
            "candidates": candidates_with_schedule,
            "subform_updated": update_success,
            "subform_skipped": subform_skipped,
            "subform_skip_reason": subform_skip_reason
        }
        
        return result


def main():
    parser = argparse.ArgumentParser(
        description="请假候选员工查询",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python leave_candidates.py --payload '{"employee_id": "E010", "start_date": "2026-06-19T16:00:00.000Z"}'
  python leave_candidates.py --payload-file webhook_payload.json
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--payload", type=str, help="Webhook payload JSON 字符串")
    group.add_argument("--payload-file", type=str, help="Webhook payload JSON 文件路径")
    
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG_PATH, help="配置文件路径")
    parser.add_argument("--output", type=str, help="结果输出文件路径（可选）")
    parser.add_argument("--dry-run", action="store_true", help="仅查询不更新子表单")
    
    args = parser.parse_args()
    
    # 解析 payload
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "error": f"Payload JSON 解析失败: {e}"
            }, ensure_ascii=False))
            sys.exit(1)
    else:
        try:
            with open(args.payload_file, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"读取 payload 文件失败: {e}"
            }, ensure_ascii=False))
            sys.exit(1)
    
    # 执行查询
    try:
        query = LeaveCandidateQuery(config_path=args.config)
        
        if args.dry_run:
            # dry-run 模式：run() 内部会检查 _dry_run 跳过写入
            payload["_dry_run"] = True
            result = query.run(payload)
            result["dry_run"] = True
        else:
            result = query.run(payload)
        
    except Exception as e:
        result = {
            "success": False,
            "error": f"执行异常: {e}"
        }
    
    # 输出结果
    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    print(output_json)
    
    # 保存到文件（如果指定）
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
    
    # 退出码
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
