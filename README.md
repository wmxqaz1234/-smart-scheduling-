# 智能排班系统 (Smart Scheduling)

基于简道云的智能排班系统，支持自动周排班、请假候选替班员工查询、排班规则校验等功能。

## 功能特性

- **每周自动排班** — 根据班次需求、员工技能等级、排班规则自动生成最优排班表
- **请假候选查询** — 员工请假时自动查询可用替班候选人，写入请假表子表单（已有数据时自动跳过）
- **排班规则校验** — 支持每周最大工作天数、连续工作天数上限等规则约束
- **技能等级匹配** — 班次可设置最低技能要求，系统自动过滤不满足的员工

## 快速开始

### 前置条件

1. 一个简道云账号，并创建好以下 5 张表单：
   - **员工信息表** — 姓名、工号、技能等级、在职状态等
   - **班次模板表** — 班次名称、时间段、所需人数、技能要求
   - **排班规则表** — 规则类型、参数值、启用状态
   - **排班结果表** — 周期、员工、日期、班次、状态
   - **请假申请表** — 工号、申请人、请假类型、日期、候选名单（子表单）

2. 获取简道云 API Key（在简道云后台 → 设置 → API Key 中生成）

### 安装步骤

```bash
# 1. 安装 Python 依赖
pip install httpx

# 2. 一键安装（自动扫描简道云表单，生成 config.json）
python scripts/install.py --app-id YOUR_APP_ID --api-key YOUR_API_KEY

# 3. 验证安装
python tests/test_smoke.py
```

安装脚本会自动完成：
- 连接简道云应用，遍历所有表单和字段
- 通过字段名称自动识别业务表和字段映射
- 生成 `config.json` 配置文件（包含所有 widget_id 映射）

> 如果一键安装失败，可使用 `python scripts/init_config.py --app-id YOUR_APP_ID --api-key YOUR_API_KEY` 手动初始化。

### 配置说明

安装后 `config.json` 会自动填入你的简道云表单 ID 和字段映射。如需修改，直接编辑此文件。

关键配置项：

| 配置项 | 说明 |
|-------|------|
| `app_id` | 简道云应用 ID |
| `api_key` | 简道云 API Key |
| `tables.*.entry_id` | 各表单的简道云表单 ID |
| `tables.*.fields` | 字段名到 widget_id 的映射 |
| `webhook_payload_fields` | Webhook 推送数据的字段映射 |

## 项目结构

```
smart-scheduling/
├── README.md                     ← 本文件
├── INSTALL.md                    ← 详细安装指南
├── SKILL.md                      ← 系统架构与算法文档
├── requirements.txt              ← Python 依赖
├── config.json                   ← 配置文件（install.py 自动生成）
├── .gitignore
├── scripts/
│   ├── scheduler.py              ← 排班算法引擎
│   ├── jdy_client.py             ← 简道云 API 客户端
│   ├── leave_candidates.py       ← 请假候选员工查询
│   ├── run_weekly_schedule.py    ← 每周排班执行脚本
│   ├── init_config.py            ← 配置自动提取
│   ├── install.py                ← 一键安装脚本
│   ├── create_pipelines.py       ← 管道创建辅助
│   ├── validate_config.py        ← 配置验证脚本
│   └── tz_util.py                ← 时区转换工具
├── pipelines/
│   ├── pipelines-meta.json       ← 自动化管道元配置
│   ├── weekly-schedule-task.md   ← 每周排班任务设计
│   └── leave-candidates-task.md  ← 请假候选任务设计
└── tests/
    └── test_smoke.py             ← 冒烟测试
```

## 自动化管道

系统支持两个自动化任务：

| 管道 | 触发方式 | 功能 |
|------|---------|------|
| 每周智能排班 | Cron（每周五 16:00） | 自动生成下周排班表 |
| 请假候选名单查询 | Webhook | 请假提交时自动查询替班候选人 |

## 技术栈

- Python 3.8+
- httpx（简道云 API 调用）
- 简道云 API v5

## License

MIT
