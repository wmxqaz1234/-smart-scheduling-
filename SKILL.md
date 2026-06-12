---
name: 智能排班
description: >
  基于简道云的智能排班系统。当用户需要生成排班表、管理员工班次、查看排班规则、处理请假调班时使用。触发词：排班、班次、排班表、值班、轮班、排班规则、请假审批。
---

# 智能排班系统

基于简道云数据 + AI 约束求解，自动生成合法、公平、高效的排班表。

---

## 系统概述

### 架构设计：两条独立流程

排班系统分为两条**独立运行**的流程，互不干扰：

```
流程 A：每周排班生成（cron 管道）
  每周五 16:00 自动触发
  → 读取员工、班次、规则（不考虑请假）
  → 运行约束求解算法
  → 写入排班结果表
  → 状态：待确认

流程 B：请假处理（webhook 管道 + 手动调整）
  员工提交请假 → webhook 实时触发
  → 查已排班员工 → 筛选候选替班人
  → 写回请假表子表单
  （后续可由 scheduler.py adjust 模式做最小幅度调整）
```

**关键设计决策**：排班生成时**不考虑请假**。请假的处理通过独立的候选推荐流程完成，排班调整通过 `scheduler.py adjust` 模式执行最小幅度交换。

### 数据模型（简道云 5 张表）

| 表名 | 核心字段 | 作用 |
|------|---------|------|
| **员工信息表** | 姓名、工号、部门、岗位、技能等级(初级/中级/高级)、每周最大天数、状态 | 员工档案 |
| **班次模板表** | 班次名称、开始时间、结束时间、时长(小时)、所需人数、班次类型(早/中/晚/全天)、所需技能 | 班次定义 |
| **排班规则表** | 规则名称、规则类型(max_consecutive_days/min_rest_hours/max_weekly_days)、参数值、优先级 | 约束配置 |
| **排班结果表** | 排班周期、员工、日期、班次、状态(待确认/已确认/已调整) | 输出 |
| **请假申请表** | 申请人、类型(请假/调班)、请假/换班日期、原因、审批状态、候选名单(子表单) | 排除约束 |

### 排班算法

算法脚本: `scripts/scheduler.py`

**结构性约束**（不可配置，物理限制）:
1. 每班次实际人数 >= 所需人数
2. 请假日期自动排除

**可配置约束**（从排班规则表读取，未配置时使用默认值或不检查）:
1. `max_shifts_per_day` — 每人每天最大班次数（默认 1）
2. `max_consecutive_days` — 连续工作天数上限（默认 6）
3. `min_rest_hours` — 两次排班最小间隔小时数（未配置时不检查）
4. `max_weekly_days` — 每周最大工作天数（默认 5）

**优化目标**:
- 班次需求满足率最大化
- 工作量公平（标准差最小化）
- 技能匹配优先

**算法流程**:
1. 计算每个 (日期, 班次) 的稀缺度 = 需求 / 可供给
2. 按稀缺度降序逐个填充
3. 每个空位选最优员工（技能 60% + 公平性 40%）
4. 全部填充后做公平性修正（过度工作者→空闲者交换）

---

## 工具依赖说明（重要）

**执行排班脚本前必须确保 bash 工具已启用**。如果遇到"工具 'bash' 当前未启用"错误：

```python
# 先调用 use_capability 启用 bash
use_capability(query="bash execute command", activate=True)

# 然后再执行排班脚本
bash(command="python3 skills/smart-scheduling/scripts/run_weekly_schedule.py --week-offset 1")
```

**为什么需要显式启用**：
- bash 工具在某些会话中不是默认可用的
- 使用 `use_capability` 可以临时激活 bash 工具
- 激活后在同一会话中可持续使用

**本技能需要的工具**：
- `bash`: 用于执行 Python 排班脚本（run_weekly_schedule.py、scheduler.py 等）
- `automation`: 用于创建和管理自动化管道（每周排班、请假候选查询）

---

## 首次使用：配置初始化

安装简道云排班应用后，**必须先运行初始化脚本**自动生成 config.json。脚本会自动遍历应用 → 表单 → 字段，识别所有 widget_id。

### 前置条件

1. 已安装简道云智能排班应用（获得 app_id）
2. 已有简道云 API Key

### 运行初始化

```bash
python skills/smart-scheduling/scripts/init_config.py \
  --app-id YOUR_APP_ID \
  --api-key YOUR_API_KEY
```

### 初始化脚本做了什么

1. 调用简道云 API 获取应用下所有表单（entry）
2. 通过表单名称匹配 5 张业务表（员工信息表、班次模板表、排班规则表、排班结果表、请假申请表）
3. 获取每张表的字段（widget），通过字段 label 匹配业务字段
4. 生成 `config.json`，包含：
   - 所有表的 entry_id 和字段 widget_id 映射
   - `webhook_payload_fields`：Webhook payload 中的字段映射
5. 验证配置完整性，报告缺失的表或字段

### 配置文件结构

生成的 `config.json` 包含：

```json
{
  "app_id": "应用ID",
  "api_key": "YOUR_API_KEY",
  "tables": {
    "employee": { "entry_id": "...", "fields": { "name": "_widget_xxx", ... } },
    "shift_template": { ... },
    "schedule_rule": { ... },
    "schedule": { ... },
    "leave": { ... }
  },
   "webhook_payload_fields": {
     "employee_id": "gonghao",
     "applicant": "shenqingren",
     "leave_date": "shijian"
   }
}
```

### 注意事项

- 初始化只需运行一次，后续字段变更时重新运行即可
- API Key 直接存储在 config.json 中，无需依赖其他 skill
- 如果表单名称或字段 label 与默认匹配规则不一致，脚本会报告未识别的项
- `webhook_payload_fields` 用于自动化管道解析 Webhook payload，确保与实际字段 ID 一致

### 工具依赖说明（重要）

**执行排班脚本前必须确保 bash 工具已启用**。如果遇到"工具 'bash' 当前未启用"错误：

```python
# 先调用 use_capability 启用 bash
use_capability(query="bash execute command", activate=True)

# 然后再执行排班脚本
bash(command="python3 skills/smart-scheduling/scripts/run_weekly_schedule.py --week-offset 1")
```

**为什么需要显式启用**：
- bash 工具在某些会话中不是默认可用的
- 使用 `use_capability` 可以临时激活 bash 工具
- 激活后在同一会话中可持续使用

### 创建自动化管道

配置初始化完成后，**必须创建两个自动化管道**以实现全自动运行。

读取 `pipelines/pipelines-meta.json` 获取管道元配置，然后对每个管道：
1. 读取对应的 `task_design_file` 获取任务设计文本
2. 调用 `automation(action="create", ...)` 创建管道

**管道 1：每周智能排班**
- 触发方式：cron `0 16 * * 5`（每周五 16:00）
- 功能：自动读取简道云数据 → 运行排班算法 → 写回排班结果表
- 任务设计文件：`pipelines/weekly-schedule-task.md`

**管道 2：请假候选名单查询**
- 触发方式：webhook（简道云请假表提交时触发）
- 功能：解析请假信息 → 查询候选替班员工 → 写回请假表子表单
- 任务设计文件：`pipelines/leave-candidates-task.md`

创建完成后，将请假管道的 Webhook URL 配置到简道云请假表的 Webhook 推送中。

---

## 完整工作流

### 场景一：自动生成下周排班

```
Step 1: 从简道云读取数据（使用内置 jdy_client.py）
  → 查询员工信息表（状态=在职）
  → 查询班次模板表
  → 查询排班规则表（启用=true）
  （不查询请假数据，排班时不考虑请假）

Step 2: 组装输入 JSON
  → 构造 employees / shifts / rules / dates 字段
  → 保存为 input.json

Step 3: 运行排班算法
  → python skills/smart-scheduling/scripts/scheduler.py generate input.json output.json

Step 4: 回写排班结果到简道云
  → 关联字段（员工、班次）使用 data_id 格式写入
  → 文本字段（工号、周期、状态）使用普通格式
  → 批量提交（batch_create，每批最多 100 条）

Step 5: 输出排班摘要
  → 填充率、人均天数、标准差、每人班次明细
```

### 场景二：查看本周排班

```
Step 1: 确定本周日期范围（周一~周日）
Step 2: 查询排班结果表，filter 日期范围
Step 3: 按日期 + 班次分组展示
```

### 场景三：处理请假后的排班调整

```
Step 1: 确认请假已审批通过
Step 2: 查询该员工在请假日期的现有排班
Step 3: 删除受影响的排班记录
Step 4: 为受影响的班次重新寻找替代人员
Step 5: 更新排班结果
```

### 场景三：请假后的最小幅度排班调整

**核心原则：只改最少的记录，不影响其他人。**

```
Step 1: 确认请假已批准，找出受影响员工的排班记录
Step 2: 构建全员排班矩阵（7天 × N人），标注请假员工的空闲日
Step 3: 寻找交换对：
  - 找一个在请假日有班、在请假员工空闲日没班的人
  - 交换这两条记录即可（2条改动）
Step 4: 如果找不到直接交换对，做链式交换：
  - A 在请假日有班 → A 给出请假日
  - A 从请假员工的空闲日拿一个班
  - 最多 2 条记录改动
Step 5: 更新简道云排班结果表
Step 6: 写入排班规则表（规则类型 = min_adjustment_swap）
```

**约束检查（交换前必须验证）：**
- 每人每周 ≤ max_weekly_days 天
- 连续工作 ≤ max_consecutive_days 天
- 两次排班间隔 ≥ min_rest_hours 小时
- 晚班需中级以上技能

**示例：**
```
李四 5/12 请假，李四空闲日: 5/13, 5/15
张三 5/12 空闲，张三 5/13 有班
→ 交换：张三拿李四的 5/12，李四拿张三的 5/13
→ 仅改 2 条记录，其他 33 条不变
```

### 场景四：新增员工/班次模板

```
直接通过内置 jdy_client.py 的 create_data 接口写入对应表单
```

---

## 简道云表单初始化指南

首次使用时，需要在简道云创建"智能排班"应用和 5 张表单。

### 创建步骤

1. 登录简道云 → 创建应用 → 命名为"智能排班系统"
2. 按下表创建 5 个表单，每个表单的字段按下方定义

### 表单字段详细定义

#### 表 1: 员工信息表

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| 姓名 | 文本 | 是 | 员工姓名 |
| 工号 | 文本 | 是 | 唯一工号 |
| 手机号 | 手机号 | 否 | 联系方式 |
| 部门 | 文本 | 是 | 所属部门 |
| 岗位 | 文本 | 是 | 岗位名称 |
| 技能等级 | 单选(初级/中级/高级) | 是 | 影响班次匹配 |
| 每周最大天数 | 数字 | 否 | 默认 5 |
| 状态 | 单选(在职/离职/休假) | 是 | 默认在职 |

#### 表 2: 班次模板表

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| 班次名称 | 文本 | 是 | 如"早班""中班""晚班" |
| 开始时间 | 文本 | 是 | 格式 HH:MM |
| 结束时间 | 文本 | 是 | 格式 HH:MM |
| 时长(小时) | 数字 | 是 | 自动计算或手动输入 |
| 所需人数 | 数字 | 是 | 每天该班次需要几人 |
| 班次类型 | 单选(早班/中班/晚班/全天) | 是 | 分类 |
| 所需技能 | 单选(无/初级/中级/高级) | 否 | 最低技能要求 |

#### 表 3: 排班规则表

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| 规则名称 | 文本 | 是 | 描述性名称 |
| 规则类型 | 单选 | 是 | max_shifts_per_day / max_consecutive_days / min_rest_hours / max_weekly_days |
| 参数值 | 数字 | 是 | 对应数值 |
| 优先级 | 数字 | 否 | 越大越优先 |
| 启用 | 布尔 | 是 | 是否生效 |

#### 表 4: 排班结果表

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| 排班周期 | 文本 | 是 | 如 "2026-W19" |
| 员工 | 关联(员工信息表) | 是 | 关联员工 |
| 日期 | 日期 | 是 | 排班日期 |
| 班次 | 关联(班次模板表) | 是 | 关联班次 |
| 状态 | 单选(待确认/已确认/已调整) | 否 | 默认待确认 |
| 备注 | 多行文本 | 否 | 特殊说明 |

#### 表 5: 请假申请表

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| 申请人 | 关联(员工信息表) | 是 | 请假人 |
| 申请类型 | 单选(请假/调班) | 是 | 类型 |
| 请假/换班日期 | 日期 | 是 | 单日期字段 |
| 原因 | 多行文本 | 否 | 说明 |
| 审批状态 | 单选(待审批/已批准/已拒绝) | 是 | 默认待审批 |
| 候选名单 | 子表单 | 否 | 自动填充候选替班员工 |

---

## 输入 JSON 格式（供 scheduler.py）

```json
{
  "period": "2026-W19",
  "dates": ["2026-05-04", "2026-05-05", "..."],
  "employees": [
    {"id": "emp_001", "name": "张三", "department": "客服部", "skill_level": "高级", "max_weekly_days": 5}
  ],
  "shifts": [
    {"id": "shift_am", "name": "早班", "start_time": "08:00", "end_time": "16:00", "required_count": 3, "required_skill": "初级"}
  ],
  "rules": [
    {"type": "max_shifts_per_day", "value": 1},
    {"type": "max_consecutive_days", "value": 6},
    {"type": "min_rest_hours", "value": 11},
    {"type": "max_weekly_days", "value": 5}
  ],
  "leaves": [
    {"employee_id": "emp_001", "leave_date": "2026-05-06", "status": "已批准"}
  ]
}
```

---

## 故障排查指南

### 问题：执行排班脚本时报错"工具 'bash' 当前未启用"

**原因**：bash 工具在当前会话中未激活。

**解决方案**：
1. 先调用 `use_capability(query="bash", activate=True)` 启用 bash 工具
2. 然后重新执行排班脚本

**预防措施**：
- 在执行任何 bash 命令前，先确认工具已启用
- 如果遇到间歇性失败（一会成功一会失败），通常是工具未启用导致

### 问题：脚本执行超时（15秒左右卡住）

**可能原因**：
1. 简道云 API 网络延迟或连接失败
2. Python 环境初始化问题
3. execute_python 工具的持久化环境问题

**排查步骤**：
1. **优先使用 bash 而非 execute_python** 执行脚本
   - execute_python 在某些环境下会超时
   - bash 更稳定可靠
2. 先用 `bash` 测试简单命令确认环境正常：
   ```bash
   echo "test" && python3 --version
   ```
3. 检查 config.json 中的 app_id 和 api_key 是否正确
4. 尝试手动运行初始化脚本验证连接

### 问题：排班结果为空或写入失败

**检查清单**：
1. 员工信息表中是否有状态="在职"的员工
2. 班次模板表是否配置了所需人数 > 0 的班次
3. 关联字段是否使用了正确的 data_id 格式（纯字符串，非数组）
4. 日期字段是否使用了 UTC 格式（通过 `bj_date_to_utc_midnight()` 转换）

### 最佳实践总结

1. **始终使用 bash 执行脚本**，避免使用 execute_python（容易超时）
2. **执行前先启用工具**：`use_capability(query="bash", activate=True)`
3. **检查返回值**：脚本执行后检查返回码和输出，确认是否成功
4. **查看完整输出**：使用 `head -100` 或重定向到文件查看完整日志

---

## 注意事项

### 基础规范

1. **字段名必须先查后用**：每次操作前调 widget/list 获取实际字段名（_widget_xxx）
2. **批量写入上限 100 条**：超过需分批
3. **排班周期命名规范**：`YYYY-WXX`（ISO 周数）
4. **算法脚本路径**：`skills/smart-scheduling/scripts/scheduler.py`，从会话目录运行
5. **简道云 API 客户端**：`skills/smart-scheduling/scripts/jdy_client.py`，内置独立客户端，不依赖 jdy-skill
6. **API Key 管理**：存储在 `skills/smart-scheduling/config.json` 的 `api_key` 字段中

### 时区处理规范（重要）

简道云 datetime 字段统一存储为 **UTC 格式**（如 `2026-06-16T00:00:00.000Z`）。
所有脚本的时区转换统一使用 `scripts/tz_util.py` 模块，禁止各脚本自行计算。

**核心转换规则**：

| 场景 | 函数 | 示例 |
|------|------|------|
| UTC 时间 → 北京时间日期 | `utc_to_bj_date()` | `"2026-06-15T16:00:00.000Z"` → `"2026-06-16"` |
| 北京时间日期 → UTC 零点格式 | `bj_date_to_utc_midnight()` | `"2026-06-16"` → `"2026-06-16T00:00:00.000Z"` |
| 北京时间日期 → UTC 查询范围 | `bj_date_to_utc_range()` | `"2026-06-16"` → `("2026-06-15T16:00:00.000Z", "2026-06-16T15:59:59.000Z")` |
| 获取当前北京时间 | `now_bjt()` | 带时区的 datetime 对象 |

**写入规则**：
- 排班结果表的日期字段必须使用 `bj_date_to_utc_midnight()` 转换后写入
- Webhook 传入的 UTC 时间必须先转北京时间再取日期

### 关联字段写入格式（关键坑）

排班结果表的「员工」和「班次」是**关联字段**（关联到员工信息表和班次模板表），写入时必须使用**被关联记录的 data_id**，格式为：

```python
# ✅ 正确格式：纯字符串
{"value": "6a27a51142f13fb09f36d086"}

# ❌ 错误格式（会静默成功但字段为空）
{"value": [{"data_id": "6a27a51142f13fb09f36d086"}]}  # 数组格式
{"value": ["6a27a51142f13fb09f36d086"]}                # 字符串数组
{"value": {"data_id": "6a27a51142f13fb09f36d086"}}     # 嵌套对象
```

**实现要点**：
1. 查询员工/班次时，用 `_id` 字段获取每条记录的 data_id
2. 构建映射表：`工号 → data_id`、`班次名 → data_id`
3. 写入排班结果时，通过映射表查找 data_id 填入关联字段
4. 同时保留文本字段（如工号）作为冗余，方便查询

### 员工状态字段

员工表的「状态」字段（`_widget_1778242620650`）存储的是**在职状态**（在职/离职），不是岗位。排班时必须过滤 `status = "在职"`，否则离职员工也会被纳入排班。

### 排班调度器调用格式

scheduler.py 有两个模式，调用时**必须指定模式参数**：

```bash
# ✅ 正确：指定 generate 模式
python scheduler.py generate <input.json> <output.json>

# ❌ 错误：缺少模式参数
python scheduler.py <input.json> <output.json>
```

### 排班结果输出格式

scheduler.py 输出的 JSON 结构为 `{"schedule": [...], "summary": {...}}`：
- 排班列表的键名是 `schedule`（不是 `assignments`）
- 每条记录包含：`employee_id`、`employee_name`、`date`、`shift_id`、`shift_name`、`start_time`、`end_time`

### 请假处理

- **候选名单推荐**：请假提交时 webhook 实时触发，**不检查审批状态**，立即推荐候选替班人
- **排班生成**：暂不考虑请假，生成纯排班表
- **排班调整**：请假批准后，可通过 `scheduler.py adjust` 模式做最小幅度交换