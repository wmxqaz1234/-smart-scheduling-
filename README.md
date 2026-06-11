# 智能排班系统 v3.0

> **推荐在 Coze、悟帆(WuFan)、WorkBuddy 等智能体平台上使用。** 本系统以 Agent 技能（Skill）的形式运行，天然适配智能体平台的自动化管道、Webhook 触发和工具调用能力。

基于简道云 + AI 约束求解的自动化排班系统。

## 快速开始

### 第一步：安装简道云应用

联系作者获取简道云排班应用模板，一键安装即可获得完整的 5 张业务表（员工信息表、班次模板表、排班规则表、排班结果表、请假申请表）。

### 第二步：初始化配置

```bash
# 安装依赖
pip install -r requirements.txt

# 生成 config.json（自动识别表结构和字段映射）
python scripts/init_config.py --app-id YOUR_APP_ID --api-key YOUR_API_KEY

# （可选）验证配置是否正确
python scripts/validate_config.py --config config.json
```

### 第三步：部署到智能体平台

将整个 `scripts/` 目录和 `config.json` 上传到你的悟帆 Agent 技能目录，然后创建两条自动化管道：

| 管道 | 触发方式 | 说明 |
|------|----------|------|
| 每周智能排班 | cron `0 16 * * 5` | 每周五 16:00 自动生成下周排班表 |
| 请假候选名单 | webhook | 员工提交请假后实时推荐候选替班人 |

管道的任务设计详见 `pipelines/` 目录。

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
