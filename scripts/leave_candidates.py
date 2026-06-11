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
        
        # API Key: 直接从 config.json 读取
        self.api_key = cfg.get("api_key", "")
        if not self.api_key:
            raise ValueError("API Key not found in config. Please run init_config.py first or set api_key in config.json")
        
        # Webhook payload 字段映射（标准名 → 实际 widget_id）
        self.webhook_payload_fields = cfg.get("webhook_payload_fields", {})
    
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
    
    def query_active_employees(self) -> List[Dict]:
        """查询在职员工列表"""
        fields = self.emp_table["fields"]
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.emp_table["entry_id"],
            "fields": [fields["name"], fields["employee_id"], fields["status"]],
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
                "status": item.get(fields["status"], "")
            })
        
        return employees
    
    def _normalize_date_to_utc_midnight(self, date_utc: str) -> str:
        """
        将日期转换为 UTC 零点格式（排班表存储格式）
        
        排班表存储格式: 2026-06-16T00:00:00.000Z (UTC 零点)
        Webhook 传入格式: 2026-06-15T16:00:00.000Z (北京时间 6月16日 00:00)
        
        转换逻辑: UTC 时间 → 北京时间日期 → UTC 零点格式
        """
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
            "limit": 1
        }
        
        result = self._api_request("/api/v5/app/entry/data/list", payload)
        
        if result.get("error"):
            return None
        
        data_list = result.get("data", [])
        if data_list:
            return data_list[0].get("_id", "")
        
        return None
    
    def update_candidates_subform(self, data_id: str, candidates: List[Dict]) -> bool:
        """更新请假表的候选子表单"""
        if not data_id:
            return False
        
        fields = self.lve_table["fields"]
        
        # 构建子表单数据
        subform_data = {
            "value": [
                {
                    fields["sub_employee_id"]: {"value": emp["employee_id"]},
                    fields["sub_name"]: {"value": emp["name"]}
                }
                for emp in candidates
            ]
        }
        
        payload = {
            "app_id": self.app_id,
            "entry_id": self.lve_table["entry_id"],
            "data_id": data_id,
            "data": {
                fields["candidates_subform"]: subform_data
            }
        }
        
        result = self._api_request("/api/v5/app/entry/data/update", payload)
        
        return not result.get("error")
    
    def run(self, payload: Dict) -> Dict:
        """
        执行完整的候选员工查询流程
        
        Args:
            payload: Webhook 传入的数据，包含：
                - employee_id: 请假员工工号
                - applicant: 申请人姓名（可选）
                - leave_date: 请假/换班日期（UTC 格式，单日期字段）
        
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
        
        # Step 2: 查询已排班员工
        scheduled_ids = self.query_scheduled_employees(start_date_utc, end_date_utc)
        
        # Step 3: 筛选候选名单
        scheduled_set = set(scheduled_ids)
        candidates = [
            emp for emp in employees
            if emp["employee_id"] not in scheduled_set
            and emp["employee_id"] != leave_employee_id
        ]
        
        # Step 4: 获取 data_id（通过工号+日期精确匹配请假记录）
        final_data_id = self.get_leave_data_id(leave_employee_id, leave_date_utc, None)
        
        # Step 5: 更新子表单（dry-run 模式跳过写入）
        dry_run = payload.get("_dry_run", False)
        update_success = False
        if candidates and final_data_id and not dry_run:
            update_success = self.update_candidates_subform(final_data_id, candidates)
        
        # 构建结果
        result = {
            "success": True,
            "leave_info": {
                "employee_id": leave_employee_id,
                "applicant": applicant,
                "leave_date_utc": leave_date_utc,
                "leave_date_display": start_display,
                "data_id": final_data_id
            },
            "statistics": {
                "total_employees": len(employees),
                "scheduled_count": len(scheduled_ids),
                "candidates_count": len(candidates)
            },
            "scheduled_ids": sorted(scheduled_ids),
            "candidates": candidates,
            "subform_updated": update_success
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
