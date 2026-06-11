#!/usr/bin/env python3
"""
简道云 API 客户端 — 智能排班系统 v3.0

独立的简道云 v5 API 客户端，不依赖 jdy-skill。
提供排班系统所需的所有数据读写操作。

用法：
    from jdy_client import JDYClient
    client = JDYClient(api_key="xxx")
    data = client.list_data(app_id, entry_id, fields=["name"], filter_cond={...})
"""

import json
import sys
import time
from typing import Dict, List, Optional, Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://api.jiandaoyun.com"


class JDYClient:
    """简道云 API 客户端"""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API Key is required")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def _request(self, endpoint: str, payload: Dict, retries: int = 2) -> Dict:
        """发送 API 请求，支持限流重试"""
        url = f"{BASE_URL}{endpoint}"
        for attempt in range(retries + 1):
            try:
                response = httpx.post(url, json=payload, headers=self.headers, timeout=30)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429 and attempt < retries:
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
                    time.sleep(1)
                    continue
                return {"error": True, "message": str(e)}
        return {"error": True, "message": "Max retries exceeded"}

    # ------------------------------------------------------------------
    # 应用/表单/字段 元数据
    # ------------------------------------------------------------------

    def list_entries(self, app_id: str) -> List[Dict]:
        """获取应用下所有表单"""
        result = self._request("/api/v5/app/entry/list", {
            "app_id": app_id,
            "limit": 100
        })
        if result.get("error"):
            return []
        return result.get("forms", result.get("data", []))

    def list_widgets(self, app_id: str, entry_id: str) -> List[Dict]:
        """获取表单的所有字段"""
        result = self._request("/api/v5/app/entry/widget/list", {
            "app_id": app_id,
            "entry_id": entry_id
        })
        if result.get("error"):
            return []
        return result.get("widgets", result.get("data", []))

    # ------------------------------------------------------------------
    # 数据读写
    # ------------------------------------------------------------------

    def list_data(self, app_id: str, entry_id: str,
                  fields: Optional[List[str]] = None,
                  filter_cond: Optional[Dict] = None,
                  limit: int = 1000) -> List[Dict]:
        """查询数据列表"""
        payload: Dict[str, Any] = {
            "app_id": app_id,
            "entry_id": entry_id,
            "limit": limit
        }
        if fields:
            payload["fields"] = fields
        if filter_cond:
            payload["filter"] = filter_cond

        result = self._request("/api/v5/app/entry/data/list", payload)
        if result.get("error"):
            return []
        return result.get("data", [])

    def create_data(self, app_id: str, entry_id: str, data: Dict) -> Dict:
        """创建一条数据"""
        result = self._request("/api/v5/app/entry/data/create", {
            "app_id": app_id,
            "entry_id": entry_id,
            "data": data
        })
        return result

    def batch_create_data(self, app_id: str, entry_id: str,
                          data_list: List[Dict], batch_size: int = 100) -> Dict:
        """批量创建数据（自动分批）"""
        created = 0
        errors = []
        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            result = self._request("/api/v5/app/entry/data/batch_create", {
                "app_id": app_id,
                "entry_id": entry_id,
                "data_list": batch
            })
            if result.get("error"):
                errors.append({"batch": i // batch_size, "error": result})
            else:
                created += len(batch)
            # 批次间隔，避免限流
            if i + batch_size < len(data_list):
                time.sleep(0.5)
        return {"created": created, "errors": errors}

    def update_data(self, app_id: str, entry_id: str,
                    data_id: str, data: Dict) -> Dict:
        """更新一条数据"""
        result = self._request("/api/v5/app/entry/data/update", {
            "app_id": app_id,
            "entry_id": entry_id,
            "data_id": data_id,
            "data": data
        })
        return result

    def delete_data(self, app_id: str, entry_id: str, data_id: str) -> Dict:
        """删除一条数据"""
        result = self._request("/api/v5/app/entry/data/delete", {
            "app_id": app_id,
            "entry_id": entry_id,
            "data_id": data_id
        })
        return result

    # ------------------------------------------------------------------
    # 便捷方法：排班场景专用
    # ------------------------------------------------------------------

    def query_employees(self, app_id: str, table_config: Dict,
                        status: str = "在职") -> List[Dict]:
        """查询在职员工"""
        fields = table_config["fields"]
        data = self.list_data(
            app_id, table_config["entry_id"],
            fields=[fields.get("name"), fields.get("employee_id"),
                    fields.get("department"), fields.get("skill_level"),
                    fields.get("max_weekly_days"), fields.get("status")],
            filter_cond={
                "rel": "and",
                "cond": [{
                    "field": fields["status"],
                    "type": "text",
                    "method": "eq",
                    "value": [status]
                }]
            }
        )
        employees = []
        for item in data:
            employees.append({
                "id": item.get(fields.get("employee_id", ""), ""),
                "name": item.get(fields.get("name", ""), ""),
                "department": item.get(fields.get("department", ""), ""),
                "skill_level": item.get(fields.get("skill_level", ""), "初级"),
                "max_weekly_days": item.get(fields.get("max_weekly_days", ""), 5),
            })
        return employees

    def query_shifts(self, app_id: str, table_config: Dict) -> List[Dict]:
        """查询班次模板"""
        fields = table_config["fields"]
        data = self.list_data(app_id, table_config["entry_id"])
        shifts = []
        for item in data:
            shifts.append({
                "id": item.get("_id", ""),
                "name": item.get(fields.get("name", ""), ""),
                "start_time": item.get(fields.get("start_time", ""), ""),
                "end_time": item.get(fields.get("end_time", ""), ""),
                "required_count": item.get(fields.get("required_count", ""), 1),
                "required_skill": item.get(fields.get("required_skill", ""), "无"),
            })
        return shifts

    def query_rules(self, app_id: str, table_config: Dict) -> List[Dict]:
        """查询排班规则（只取启用的）"""
        fields = table_config["fields"]
        data = self.list_data(app_id, table_config["entry_id"])
        rules = []
        for item in data:
            enabled = item.get(fields.get("enabled", ""), True)
            if enabled in (True, "是", "true", "1", 1):
                rules.append({
                    "type": item.get(fields.get("rule_type", ""), ""),
                    "value": item.get(fields.get("param_value", ""), 0),
                })
        return rules

    def query_approved_leaves(self, app_id: str, table_config: Dict,
                              start_date: str, end_date: str) -> List[Dict]:
        """查询已批准的请假"""
        fields = table_config["fields"]
        data = self.list_data(
            app_id, table_config["entry_id"],
            filter_cond={
                "rel": "and",
                "cond": [
                    {
                        "field": fields.get("approval_status", ""),
                        "type": "text",
                        "method": "eq",
                        "value": ["已批准"]
                    },
                    {
                        "field": fields.get("start_date", ""),
                        "type": "datetime",
                        "method": "range",
                        "value": [start_date, end_date]
                    }
                ]
            }
        )
        leaves = []
        for item in data:
            leaves.append({
                "employee_id": item.get(fields.get("employee_id", ""), ""),
                "start_date": item.get(fields.get("start_date", ""), "")[:10],
                "end_date": item.get(fields.get("end_date", ""), "")[:10],
                "status": "已批准"
            })
        return leaves

    def write_schedule(self, app_id: str, table_config: Dict,
                       schedule_list: List[Dict]) -> Dict:
        """批量写入排班结果"""
        fields = table_config["fields"]
        data_list = []
        for item in schedule_list:
            row = {}
            if "period" in fields:
                row[fields["period"]] = {"value": item.get("period", "")}
            if "employee_id" in fields:
                row[fields["employee_id"]] = {"value": item.get("employee_id", "")}
            if "date" in fields:
                row[fields["date"]] = {"value": item.get("date", "")}
            if "shift" in fields:
                row[fields["shift"]] = {"value": item.get("shift_id", "")}
            if "status" in fields:
                row[fields["status"]] = {"value": item.get("status", "待确认")}
            data_list.append(row)
        return self.batch_create_data(app_id, table_config["entry_id"], data_list)
