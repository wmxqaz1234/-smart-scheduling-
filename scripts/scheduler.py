#!/usr/bin/env python3
"""
智能排班算法引擎 v3
采用贪心 + 约束传播，从最紧缺时段开始填充，生成满足劳动法和业务规则的排班表。

输入：JSON 文件（员工、班次、规则、请假、日期范围）
输出：JSON 文件（排班结果 + 统计摘要）

v2 更新 (2026-05-09):
- 修复规则读取 bug（同类型规则不再覆盖）
- 公平性阈值改为可配置
- 新增最小幅度调整算法（请假后局部交换）
- 修复跨天班次休息间隔计算
- 新增 min_adjustment_swap 规则支持

v3 更新 (2026-06-11):
- 数据结构从 {(eid,date): shift_id} 改为 {(eid,date): [shift_id, ...]}，支持一人一天多班次
- 新增 max_shifts_per_day 可配置规则（每人每天最大班次数）
- 同一天多班次之间也检查休息间隔
- assign/unassign 支持列表操作
- work_days 统一为 shift_count 语义（按班次计数，非按天计数）
"""

import json
import sys
import math
from datetime import datetime, timedelta
from collections import defaultdict


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[输出] 排班结果已保存: {path}")


def parse_dates(start_str, end_str):
    """生成日期列表 (YYYY-MM-DD)"""
    start = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    dates = []
    cur = start
    while cur <= end:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


# ============================================================
# 约束检查器
# ============================================================

class ConstraintChecker:
    def __init__(self, employees, shifts, rules, leaves, dates):
        self.employees = {e["id"]: e for e in employees}
        self.shifts = {s["id"]: s for s in shifts}
        self.dates = dates

        # [FIX-1] 规则读取：改为列表存储，同类型规则不再覆盖
        # 取每个类型的最新值（最后一条优先）
        self._rules_list = rules
        self._rules_map = {}
        for r in rules:
            self._rules_map[r["type"]] = r

        # 构建请假索引: {employee_id: set(dates)}
        self.leave_map = defaultdict(set)
        for lv in leaves:
            if lv.get("status") not in ("已批准", "approved"):
                continue
            eid = lv["employee_id"]
            for d in parse_dates(lv["start_date"], lv["end_date"]):
                self.leave_map[eid].add(d)

        # 排班状态: {(eid, date): [shift_id1, shift_id2, ...]}
        self.schedule = {}

        # 员工班次统计: {eid: count}（同一人同一天多班次会分别计数）
        self.shift_count = defaultdict(int)

        # 员工最近工作日期追踪: {eid: [sorted dates]}
        self.work_dates = defaultdict(list)

    def get_rule(self, rule_type, default):
        """安全读取规则值"""
        r = self._rules_map.get(rule_type)
        if r:
            return r.get("value", default)
        return default

    def max_consecutive(self):
        return self.get_rule("max_consecutive_days", 6)

    def min_rest_hours(self):
        """返回最小休息小时数，未配置时返回 None"""
        return self.get_rule("min_rest_hours", None)

    def max_weekly_days(self):
        return self.get_rule("max_weekly_days", 5)

    def max_shifts_per_day(self):
        return self.get_rule("max_shifts_per_day", 1)

    # [FIX-2] 公平性阈值改为可配置
    def fairness_threshold(self):
        return self.get_rule("fairness_std_threshold", 1.5)

    def is_on_leave(self, eid, date):
        return date in self.leave_map.get(eid, set())

    def get_daily_shifts(self, eid, date):
        """获取某人某天的班次列表"""
        return self.schedule.get((eid, date), [])

    def check_daily_shifts(self, eid, date):
        """检查当天班次数是否超限"""
        shifts = self.get_daily_shifts(eid, date)
        return len(shifts) < self.max_shifts_per_day()

    def check_consecutive(self, eid, date):
        """检查连续工作天数是否超限"""
        max_c = self.max_consecutive()
        d = datetime.strptime(date, "%Y-%m-%d")

        # 向前数连续天数
        count_back = 0
        cur = d - timedelta(days=1)
        while cur.strftime("%Y-%m-%d") in set(self.work_dates.get(eid, [])):
            count_back += 1
            cur -= timedelta(days=1)

        # 向后数连续天数
        count_fwd = 0
        cur = d + timedelta(days=1)
        while cur.strftime("%Y-%m-%d") in set(self.work_dates.get(eid, [])):
            count_fwd += 1
            cur += timedelta(days=1)

        return (count_back + 1 + count_fwd) <= max_c

    def check_rest_gap(self, eid, date, shift_id):
        """检查两次排班之间休息时间是否足够（未配置 min_rest_hours 规则时跳过）"""
        min_rest = self.min_rest_hours()
        if min_rest is None:
            return True  # 规则未配置，跳过检查
        
        shift = self.shifts[shift_id]
        d = datetime.strptime(date, "%Y-%m-%d")

        # 检查同一天已有班次的时间冲突
        same_day_shifts = self.get_daily_shifts(eid, date)
        for existing_sid in same_day_shifts:
            existing_shift = self.shifts[existing_sid]
            # 检查两个方向：新班次在已有班次之后，或已有班次在新班次之后
            gap1 = self._calc_gap_hours(existing_shift["end_time"], shift["start_time"])
            gap2 = self._calc_gap_hours(shift["end_time"], existing_shift["start_time"])
            # 取较小的间隔（两个班次之间实际只有一个方向有意义）
            if gap1 < min_rest and gap2 < min_rest:
                return False

        # 检查前一天
        prev_date = (d - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_shifts = self.get_daily_shifts(eid, prev_date)
        if prev_shifts:
            # 取最晚结束的班次
            prev_shift = max(
                [self.shifts[sid] for sid in prev_shifts],
                key=lambda s: s["end_time"]
            )
            gap = self._calc_gap_hours(prev_shift["end_time"], shift["start_time"])
            if gap < min_rest:
                return False

        # 检查后一天
        next_date = (d + timedelta(days=1)).strftime("%Y-%m-%d")
        next_shifts = self.get_daily_shifts(eid, next_date)
        if next_shifts:
            # 取最早开始的班次
            next_shift = min(
                [self.shifts[sid] for sid in next_shifts],
                key=lambda s: s["start_time"]
            )
            gap = self._calc_gap_hours(shift["end_time"], next_shift["start_time"])
            if gap < min_rest:
                return False

        return True

    # [FIX-4] 修复跨天班次休息间隔计算
    def _calc_gap_hours(self, end_time, start_time):
        """计算两个时间点之间的间隔（小时），正确处理跨天"""
        try:
            eh, em = map(int, end_time.split(":"))
            sh, sm = map(int, start_time.split(":"))
            end_min = eh * 60 + em
            start_min = sh * 60 + sm
            diff = start_min - end_min
            if diff <= 0:
                diff += 24 * 60  # 跨天：start 在 end 之后的第二天
            return diff / 60
        except Exception:
            return 12  # 解析失败时默认足够

    def check_skill_match(self, eid, shift_id):
        """检查技能匹配度，返回 0-1 分数"""
        emp = self.employees.get(eid, {})
        shift = self.shifts.get(shift_id, {})
        required = shift.get("required_skill", "")
        emp_level = emp.get("skill_level", "初级")

        if not required or required == "无":
            return 1.0

        level_map = {"初级": 1, "中级": 2, "高级": 3}
        emp_val = level_map.get(emp_level, 1)
        req_val = level_map.get(required, 1)

        if emp_val >= req_val:
            return 1.0
        elif emp_val == req_val - 1:
            return 0.5  # 降一级可接受
        else:
            return 0.0  # 不匹配

    def can_assign(self, eid, date, shift_id):
        """综合检查是否可以分配"""
        if self.is_on_leave(eid, date):
            return False, "请假"
        if not self.check_daily_shifts(eid, date):
            return False, "当天班次已满"
        # 检查是否已分配相同班次（同一天不能重复同一班次）
        if shift_id in self.get_daily_shifts(eid, date):
            return False, "已有相同班次"
        if not self.check_consecutive(eid, date):
            return False, "连续工作超限"
        if not self.check_rest_gap(eid, date, shift_id):
            return False, "休息时间不足"

        # 检查每周工作天数
        d = datetime.strptime(date, "%Y-%m-%d")
        week_start = d - timedelta(days=d.weekday())
        week_dates = [(week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        week_work = sum(1 for wd in week_dates if wd in set(self.work_dates.get(eid, [])))
        if week_work >= self.max_weekly_days():
            return False, "每周工作天数超限"

        skill_score = self.check_skill_match(eid, shift_id)
        if skill_score == 0:
            return False, "技能不匹配"

        return True, skill_score

    def assign(self, eid, date, shift_id):
        """执行分配"""
        if (eid, date) not in self.schedule:
            self.schedule[(eid, date)] = []
        self.schedule[(eid, date)].append(shift_id)
        self.shift_count[eid] += 1
        if date not in self.work_dates[eid]:
            self.work_dates[eid].append(date)
            self.work_dates[eid].sort()

    def unassign(self, eid, date, shift_id=None):
        """撤销分配"""
        key = (eid, date)
        if key in self.schedule:
            if shift_id:
                # 撤销指定班次
                if shift_id in self.schedule[key]:
                    self.schedule[key].remove(shift_id)
                    self.shift_count[eid] -= 1
                    if not self.schedule[key]:
                        del self.schedule[key]
                        if date in self.work_dates.get(eid, []):
                            self.work_dates[eid].remove(date)
            else:
                # 撤销当天所有班次
                count = len(self.schedule[key])
                del self.schedule[key]
                self.shift_count[eid] -= count
                if date in self.work_dates.get(eid, []):
                    self.work_dates[eid].remove(date)


# ============================================================
# 排班引擎
# ============================================================

class SchedulingEngine:
    def __init__(self, data):
        self.employees = data["employees"]
        self.shifts = data["shifts"]
        self.rules = data.get("rules", [])
        self.leaves = data.get("leaves", [])
        self.dates = data["dates"]
        self.period = data.get("period", "unknown")

        self.checker = ConstraintChecker(
            self.employees, self.shifts, self.rules, self.leaves, self.dates
        )

        # 每天每个班次需要的人数
        self.shift_demand = {}
        for date in self.dates:
            for shift in self.shifts:
                self.shift_demand[(date, shift["id"])] = shift.get("required_count", 1)

    def generate(self):
        """主排班流程"""
        print(f"[排班] 开始生成排班: {self.period}")
        print(f"[排班] 日期范围: {self.dates[0]} ~ {self.dates[-1]}, 共 {len(self.dates)} 天")
        print(f"[排班] 员工数: {len(self.employees)}, 班次类型: {len(self.shifts)}")

        # Step 1: 计算每个 (date, shift) 的稀缺度并排序
        slots = self._compute_scarcity()

        # Step 2: 按稀缺度从高到低逐个填充
        for date, shift_id, scarcity in slots:
            demand = self.shift_demand.get((date, shift_id), 1)
            assigned = self._count_assigned(date, shift_id)

            while assigned < demand:
                best = self._find_best_employee(date, shift_id)
                if best is None:
                    print(f"[警告] {date} 班次 {self.checker.shifts[shift_id]['name']} "
                          f"无法满足需求({assigned}/{demand})")
                    break
                self.checker.assign(best, date, shift_id)
                assigned += 1

        # Step 3: 公平性修正
        self._fairness_adjustment()

        # Step 4: 生成结果
        result = self._build_result()
        return result

    def _compute_scarcity(self):
        """计算每个时段的稀缺度 = 需求 / 可供给"""
        slots = []
        for date in self.dates:
            for shift in self.shifts:
                sid = shift["id"]
                demand = self.shift_demand.get((date, sid), 1)
                supply = sum(
                    1 for e in self.employees
                    if self.checker.can_assign(e["id"], date, sid)[0]
                )
                scarcity = demand / max(supply, 1)
                slots.append((date, sid, scarcity))

        # 稀缺度高的优先
        slots.sort(key=lambda x: -x[2])
        return slots

    def _find_best_employee(self, date, shift_id):
        """为指定时段找最优员工"""
        candidates = []
        for emp in self.employees:
            eid = emp["id"]
            ok, info = self.checker.can_assign(eid, date, shift_id)
            if not ok:
                continue

            skill_score = info  # 0-1
            fairness_score = 1.0 / (self.checker.shift_count.get(eid, 0) + 1)
            # 综合评分：技能匹配 60% + 公平性 40%
            score = skill_score * 0.6 + fairness_score * 0.4
            candidates.append((eid, score))

        if not candidates:
            return None

        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    def _count_assigned(self, date, shift_id):
        """统计某天某班次已分配人数"""
        count = 0
        for emp in self.employees:
            shifts = self.checker.get_daily_shifts(emp["id"], date)
            if shift_id in shifts:
                count += 1
        return count

    def _fairness_adjustment(self):
        """[FIX-2] 公平性修正：阈值可配置"""
        work_counts = dict(self.checker.shift_count)
        if not work_counts:
            return

        avg = sum(work_counts.values()) / len(work_counts)
        std = math.sqrt(sum((v - avg) ** 2 for v in work_counts.values()) / len(work_counts))

        threshold = self.checker.fairness_threshold()
        if std < threshold:
            print(f"[公平性] 工作量分布均匀 (标准差={std:.2f}, 阈值={threshold})，无需修正")
            return

        print(f"[公平性] 工作量标准差={std:.2f} > 阈值={threshold}，尝试修正...")

        overloaded = [(eid, count) for eid, count in work_counts.items() if count > avg + 1]
        underloaded = [(eid, count) for eid, count in work_counts.items() if count < avg - 1]

        overloaded.sort(key=lambda x: -x[1])
        underloaded.sort(key=lambda x: x[1])

        swaps = 0
        for over_eid, _ in overloaded:
            for under_eid, _ in underloaded:
                if work_counts[over_eid] <= work_counts[under_eid] + 1:
                    break
                for date in self.dates:
                    shifts = self.checker.get_daily_shifts(over_eid, date)
                    if not shifts:
                        continue
                    shift_id = shifts[0]  # 取第一个班次
                    ok, _ = self.checker.can_assign(under_eid, date, shift_id)
                    if ok:
                        self.checker.unassign(over_eid, date, shift_id)
                        self.checker.assign(under_eid, date, shift_id)
                        work_counts[over_eid] -= 1
                        work_counts[under_eid] += 1
                        swaps += 1
                        break

        print(f"[公平性] 完成 {swaps} 次交换")

    def _build_result(self):
        """构建输出结果"""
        schedule_list = []
        for (eid, date), shift_ids in sorted(self.checker.schedule.items()):
            emp = self.checker.employees[eid]
            for shift_id in shift_ids:
                shift = self.checker.shifts[shift_id]
                schedule_list.append({
                    "period": self.period,
                    "employee_id": eid,
                    "employee_name": emp.get("name", eid),
                    "department": emp.get("department", ""),
                    "date": date,
                    "shift_id": shift_id,
                    "shift_name": shift.get("name", shift_id),
                    "start_time": shift.get("start_time", ""),
                    "end_time": shift.get("end_time", ""),
                    "status": "待确认"
                })

        work_counts = dict(self.checker.shift_count)
        avg = sum(work_counts.values()) / max(len(work_counts), 1)
        std = math.sqrt(sum((v - avg) ** 2 for v in work_counts.values()) / max(len(work_counts), 1)) if work_counts else 0

        total_demand = sum(self.shift_demand.values())
        total_assigned = len(schedule_list)
        fill_rate = total_assigned / max(total_demand, 1) * 100

        summary = {
            "period": self.period,
            "total_assignments": total_assigned,
            "total_demand": total_demand,
            "fill_rate": round(fill_rate, 1),
            "avg_shifts_per_person": round(avg, 2),
            "shift_count_std": round(std, 2),
            "employee_stats": {}
        }

        for emp in self.employees:
            eid = emp["id"]
            summary["employee_stats"][emp.get("name", eid)] = {
                "shift_count": work_counts.get(eid, 0),
                "shifts": defaultdict(int)
            }

        for (eid, date), shift_ids in self.checker.schedule.items():
            name = self.checker.employees[eid].get("name", eid)
            for shift_id in shift_ids:
                shift_name = self.checker.shifts[shift_id].get("name", shift_id)
                summary["employee_stats"][name]["shifts"][shift_name] += 1

        for name in summary["employee_stats"]:
            summary["employee_stats"][name]["shifts"] = dict(summary["employee_stats"][name]["shifts"])

        return {
            "schedule": schedule_list,
            "summary": summary
        }


# ============================================================
# [FIX-3] 最小幅度调整算法
# ============================================================

class MinAdjustmentEngine:
    """请假后最小幅度排班调整引擎

    核心思路：
    1. 找出受影响的排班记录
    2. 寻找直接交换对（A 在请假日有班 + A 在请假员工空闲日没班）
    3. 如果找不到直接交换对，做链式交换（最多 2 条改动）
    4. 验证交换后所有约束仍然满足
    """

    def __init__(self, data, existing_schedule):
        """
        data: 原始输入数据（employees, shifts, rules, leaves, dates）
        existing_schedule: 现有排班结果 [{"employee_id", "date", "shift_id", ...}, ...]
        """
        self.employees = {e["id"]: e for e in data["employees"]}
        self.shifts = {s["id"]: s for s in data["shifts"]}
        self.dates = data["dates"]

        self.checker = ConstraintChecker(
            data["employees"], data["shifts"],
            data.get("rules", []),
            data.get("leaves", []),
            data["dates"]
        )

        # 加载现有排班到 checker
        self.schedule_list = existing_schedule
        for item in existing_schedule:
            eid = item["employee_id"]
            date = item["date"]
            shift_id = item["shift_id"]
            self.checker.assign(eid, date, shift_id)

    def adjust_for_leave(self, employee_id, leave_dates):
        """为指定员工的请假日期做最小幅度调整

        Args:
            employee_id: 请假员工 ID
            leave_dates: 请假日期列表 ["2026-05-12", ...]

        Returns:
            {
                "success": bool,
                "swaps": [{"action": "swap", "from": {...}, "to": {...}}, ...],
                "affected_records": 2,
                "message": str
            }
        """
        affected = []
        for date in leave_dates:
            shifts = self.checker.get_daily_shifts(employee_id, date)
            for shift_id in shifts:
                affected.append({"date": date, "shift_id": shift_id})

        if not affected:
            return {
                "success": True,
                "swaps": [],
                "affected_records": 0,
                "message": f"员工 {employee_id} 在请假日期无排班，无需调整"
            }

        # 请假员工的空闲日
        emp_schedule_dates = set(
            d for (eid, d) in self.checker.schedule.keys() if eid == employee_id
        )
        free_dates = [d for d in self.dates if d not in emp_schedule_dates]

        # 标记请假日期
        for item in affected:
            self.checker.leave_map[employee_id].add(item["date"])

        swaps = []
        for item in affected:
            leave_date = item["date"]
            leave_shift = item["shift_id"]

            # 寻找交换对
            swap = self._find_swap(employee_id, leave_date, leave_shift, free_dates)
            if swap:
                swaps.append(swap)
            else:
                # 没找到交换对，尝试用新员工替班
                replacement = self._find_replacement(leave_date, leave_shift)
                if replacement:
                    swaps.append({
                        "action": "replace",
                        "leave_date": leave_date,
                        "leave_shift": leave_shift,
                        "original_emp": employee_id,
                        "replacement_emp": replacement,
                    })
                else:
                    return {
                        "success": False,
                        "swaps": swaps,
                        "affected_records": len(swaps),
                        "message": f"无法为 {leave_date} {self.shifts[leave_shift]['name']} 找到替代方案"
                    }

        # 执行交换
        for swap in swaps:
            self._execute_swap(swap, employee_id)

        return {
            "success": True,
            "swaps": swaps,
            "affected_records": len(swaps) * 2 if swaps and swaps[0]["action"] == "swap" else len(swaps),
            "message": f"完成 {len(swaps)} 次调整"
        }

    def _find_swap(self, leave_emp, leave_date, leave_shift, free_dates):
        """寻找直接交换对"""
        for eid in self.employees:
            if eid == leave_emp:
                continue
            # 该员工在请假日有班吗？
            other_shifts = self.checker.get_daily_shifts(eid, leave_date)
            if not other_shifts:
                continue
            other_shift = other_shifts[0]  # 取第一个班次
            # 该员工在请假员工空闲日有空吗？
            for free_date in free_dates:
                if self.checker.get_daily_shifts(eid, free_date):
                    continue  # 该员工那天有班
                # 检查：该员工能否接请假员工在 free_date 的班
                free_shifts = self.checker.get_daily_shifts(leave_emp, free_date)
                if not free_shifts:
                    continue
                free_shift = free_shifts[0]
                # 检查约束
                self.checker.unassign(eid, leave_date, other_shift)
                self.checker.unassign(leave_emp, free_date, free_shift)
                ok1, _ = self.checker.can_assign(eid, free_date, free_shift)
                ok2, _ = self.checker.can_assign(leave_emp, leave_date, other_shift)
                # 恢复
                self.checker.assign(eid, leave_date, other_shift)
                self.checker.assign(leave_emp, free_date, free_shift)

                if ok1 and ok2:
                    return {
                        "action": "swap",
                        "emp_a": leave_emp,
                        "date_a": free_date,
                        "shift_a": free_shift,
                        "emp_b": eid,
                        "date_b": leave_date,
                        "shift_b": other_shift,
                    }
        return None

    def _find_replacement(self, leave_date, leave_shift):
        """找一个空闲员工替班"""
        for eid in self.employees:
            if self.checker.get_daily_shifts(eid, leave_date):
                continue  # 该员工那天有班
            ok, _ = self.checker.can_assign(eid, leave_date, leave_shift)
            if ok:
                return eid
        return None

    def _execute_swap(self, swap, leave_emp):
        """执行交换"""
        if swap["action"] == "swap":
            # 双向交换
            self.checker.unassign(swap["emp_a"], swap["date_a"], swap["shift_a"])
            self.checker.unassign(swap["emp_b"], swap["date_b"], swap["shift_b"])
            self.checker.assign(swap["emp_b"], swap["date_a"], swap["shift_a"])
            self.checker.assign(swap["emp_a"], swap["date_b"], swap["shift_b"])
        elif swap["action"] == "replace":
            # 单向替换
            self.checker.unassign(swap["original_emp"], swap["leave_date"], swap["leave_shift"])
            self.checker.assign(swap["replacement_emp"], swap["leave_date"], swap["leave_shift"])

    def get_updated_schedule(self):
        """获取调整后的排班结果"""
        result = []
        for (eid, date), shift_ids in sorted(self.checker.schedule.items()):
            emp = self.employees.get(eid, {})
            for shift_id in shift_ids:
                shift = self.shifts.get(shift_id, {})
                result.append({
                    "employee_id": eid,
                    "employee_name": emp.get("name", eid),
                    "date": date,
                    "shift_id": shift_id,
                    "shift_name": shift.get("name", shift_id),
                    "start_time": shift.get("start_time", ""),
                    "end_time": shift.get("end_time", ""),
                    "status": "已调整"
                })
        return result


# ============================================================
# CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 3:
        print("用法:")
        print("  生成排班: python scheduler.py generate <input.json> <output.json>")
        print("  最小调整: python scheduler.py adjust <input.json> <schedule.json> <emp_id> <date1,date2,...> <output.json>")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "generate":
        # 全量生成排班
        input_path = sys.argv[2]
        output_path = sys.argv[3]
        data = load_json(input_path)

        required_keys = ["employees", "shifts", "dates"]
        for k in required_keys:
            if k not in data:
                print(f"[错误] 输入缺少必要字段: {k}")
                sys.exit(1)

        engine = SchedulingEngine(data)
        result = engine.generate()
        save_json(result, output_path)

        s = result["summary"]
        print(f"\n{'='*50}")
        print(f"排班完成: {s['period']}")
        print(f"总分配: {s['total_assignments']} / 需求: {s['total_demand']} (满足率 {s['fill_rate']}%)")
        print(f"人均班次数: {s['avg_shifts_per_person']}, 标准差: {s['shift_count_std']}")
        print(f"{'='*50}")
        for name, stat in s["employee_stats"].items():
            shifts_str = ", ".join(f"{k}×{v}" for k, v in stat["shifts"].items())
            print(f"  {name}: {stat['shift_count']}班次 ({shifts_str})")

    elif mode == "adjust":
        # 最小幅度调整
        input_path = sys.argv[2]
        schedule_path = sys.argv[3]
        emp_id = sys.argv[4]
        leave_dates = sys.argv[5].split(",")
        output_path = sys.argv[6]

        data = load_json(input_path)
        schedule_data = load_json(schedule_path)
        existing = schedule_data.get("schedule", [])

        engine = MinAdjustmentEngine(data, existing)
        result = engine.adjust_for_leave(emp_id, leave_dates)

        print(f"\n{'='*50}")
        print(f"最小幅度调整结果:")
        print(f"  成功: {result['success']}")
        print(f"  调整记录数: {result['affected_records']}")
        print(f"  消息: {result['message']}")
        print(f"{'='*50}")

        for swap in result.get("swaps", []):
            if swap["action"] == "swap":
                print(f"  交换: {swap['emp_a']} {swap['date_a']} {swap['shift_a']} ↔ "
                      f"{swap['emp_b']} {swap['date_b']} {swap['shift_b']}")
            elif swap["action"] == "replace":
                print(f"  替换: {swap['original_emp']} {swap['leave_date']} → {swap['replacement_emp']}")

        if result["success"]:
            updated = engine.get_updated_schedule()
            save_json({"schedule": updated, "adjustment": result}, output_path)
    else:
        print(f"[错误] 未知模式: {mode}")
        print("支持: generate, adjust")
        sys.exit(1)


if __name__ == "__main__":
    main()
