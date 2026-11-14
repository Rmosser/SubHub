# Secret Rotation Policy

## 范围

- 实例级密钥：`/lzcapp/var/data/instance_secrets.json` 中的 `data_encryption_key`
- 用户级订阅 token：`user_sub_tokens`

## 规则

1. 分发包内禁止真实密钥，只允许占位符
2. 实例级密钥默认不轮换；轮换必须带数据迁移方案
3. 用户级订阅 token 可轮换；轮换后旧 token 立即失效

## 实例级密钥

- 作用：解密已落库敏感字段
- 直接变更结果：触发 `DATA_ENCRYPTION_KEY mismatch`，服务拒绝启动

执行规则：

1. 非必要不轮换
2. 必须轮换时，先做全量导出和迁移演练
3. 在停机窗口执行迁移

## 用户级 SUB_TOKEN

- token 与 `owner_user_id` 一一对应
- 写入新 token 后，旧 token 立即失效

执行规则：

1. 怀疑泄漏时立即轮换
2. 轮换后验证：
   - 新 token 访问 `/sub/*` 返回 `200/403`
   - 旧 token 返回 `403 invalid token`

## 策略备份 GitHub token

- `POLICY_BACKUP_GITHUB_TOKEN` 仅从运行时密钥注入读取，不得写入
  `lzc-manifest.yml`、镜像、LPK 或提交历史。
- 生产环境将该变量配置在懒猫实例的受控 Secret/环境注入中；源码仓库中的
  manifest 只保留空值或占位符。
- 使用最小范围、仅可写入策略备份仓库的凭证；轮换后先验证一次“立即同步”，
  再确认日志和状态只显示仓库、分支、提交摘要等非秘密元数据。

## 发布前检查

```bash
scripts/security_preflight.sh
```

确认：

- `lzc-manifest.yml` 仍为占位符密钥
- 文档不包含本机绝对路径
- `.lpk` 不包含 `.env`、`var/`、`*.db`、`*.pyc`、私钥文件
