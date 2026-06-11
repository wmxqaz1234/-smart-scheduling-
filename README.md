# 智能排班系统 v3.0

> **推荐在 Coze、悟帆(WuFan)、WorkBuddy 等智能体平台上使用。** 本系统以 Agent 技能（Skill）的形式运行，天然适配智能体平台的自动化管道、Webhook 触发和工具调用能力。

基于简道云 + AI 约束求解的自动化排班系统。

## 快速开始

### 第一步：安装简道云应用

联系作者获取简道云排班应用模板，一键安装即可获得完整的 5 张业务表（员工信息表、班次模板表、排班规则表、排班结果表、请假申请表）。

### 第二步：告诉智能体你的应用信息

在对话中提供以下信息，智能体会自动完成配置初始化、验证和管道创建：

> 我的简道云排班应用 app_id 是 xxx，api_key 是 xxx，帮我初始化排班系统，项目链接是 https://github.com/wmxqaz1234/-smart-scheduling- 。

智能体会自动执行：安装依赖 → 生成配置 → 验证表结构 → 创建自动化管道。完成后即可直接使用。

### 第三步：开始使用

配置完成后，系统自动运行：

- **每周五 16:00** 自动生成下周排班表
- **员工提交请假时** 实时推荐候选替班人

也可以随时对话操作："帮我生成下周一的排班表"、"张三请假了，推荐一下替班人"。

## 功能

- **自动排班生成**：每周五自动读取员工、班次、规则数据，运行约束求解算法生成排班表
- **请假候选推荐**：员工提交请假后实时触发，自动筛选候选替班人
- **约束求解**：支持连续工作天数、每周最大天数、最小休息间隔、技能匹配等约束
- **公平性优化**：贪心填充 + 公平性修正，确保工作量均匀分配

## 文件结构

```
├── README.md                         # 本文件
├── SKILL.md                          # 技能定义（Agent 加载用）
├── INSTALL.md                        # 详细安装指南
├── requirements.txt                  # Python 依赖
├── config.json                       # 运行时配置（init_config.py 生成）
├── scripts/
│   ├── scheduler.py                  # 核心排班算法
│   ├── jdy_client.py                 # 简道云 API 客户端
│   ├── tz_util.py                    # 时区工具模块
│   ├── leave_candidates.py           # 请假候选推荐
│   ├── run_weekly_schedule.py        # 每周排班流程脚本
│   ├── init_config.py                # 配置初始化
│   ├── validate_config.py            # 配置验证（建表后检查）
│   ├── install.py                    # 一键安装
│   └── create_pipelines.py           # 管道创建
├── pipelines/
│   ├── pipelines-meta.json           # 管道元配置
│   ├── weekly-schedule-task.md       # 排班管道任务设计
│   └── leave-candidates-task.md      # 请假管道任务设计
└── tests/
    └── test_smoke.py                 # 冒烟测试（4 个用例）
```

## 核心算法

scheduler.py 采用贪心 + 公平性修正的约束求解策略：

1. 计算每个（日期, 班次）的稀缺度
2. 按稀缺度降序逐个填充
3. 每个空位选择最优员工（技能 60% + 公平性 40%）
4. 全部填充后做公平性交换修正

支持两种模式：`generate`（全量排班）和 `adjust`（最小幅度调整）。

## 数据模型

依赖简道云 5 张业务表：员工信息表、班次模板表、排班规则表、排班结果表、请假申请表。

详见 [SKILL.md](./SKILL.md) 和 [INSTALL.md](./INSTALL.md)。

## 时区规范

所有时间处理统一使用 `scripts/tz_util.py` 模块。简道云 datetime 字段存储为 UTC，北京时间 = UTC + 8 小时。

## License

MIT
