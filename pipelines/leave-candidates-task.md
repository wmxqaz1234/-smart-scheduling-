# 请假候选员工查询

简道云请假表提交 → Webhook 推送 → 调用脚本查询候选替班员工。

## 执行

使用 bash 执行以下命令（一条命令完成全部逻辑）：

```bash
python skills/smart-scheduling/scripts/leave_candidates.py --payload '{{payload}}'
```

## 输出

脚本会自动完成：
1. 解析 Webhook payload 中的请假人工号、请假日期
2. 查询该日期已排班的其他员工
3. 筛选可用候选员工（排除已排班者 + 请假者本人）
4. 将候选名单写回请假表的子表单

## Webhook Payload 字段映射

| payload 字段 | 说明 |
|-------------|------|
| gonghao | 请假人工号 |
| shenqingren | 请假人姓名 |
| shijian | 请假/换班日期（单日期字段，UTC 格式） |

## 异常处理

- 如果 payload 缺少必要字段，脚本会报错并列出缺失字段
- 如果找不到候选员工，脚本会输出"无可用候选"并建议调整排班规则
