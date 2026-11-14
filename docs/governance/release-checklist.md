# Release Checklist

## 功能检查

- [ ] `/manage` 可作为默认管理入口打开
- [ ] 后台可登录
- [ ] 至少一个账号采集成功
- [ ] 至少一个设备生成订阅链接
- [ ] Clash 订阅可下载
- [ ] 在线 Clash blocker 场景返回 `409 clash-build-blocked`
- [ ] Shadowrocket 订阅可下载
- [ ] Surge 订阅可下载
- [ ] 管理端 Clash 离线审核包可导出
- [ ] `AUDIT.md` 已包含 warning / blocker 摘要

## 可靠性检查

- [ ] `/healthz` 返回 `ok=true`
- [ ] `last_error` 无阻断错误
- [ ] 规则缓存文件存在：`/lzcapp/var/cache/rules_snapshot.json`
- [ ] 未初始化实例验证通过：`/manage` 仍可作为默认入口打开、`/setup` 初始化门禁可达、`/sub/* -> 503 setup required`

## 文档检查

- [ ] `docs/api/http-api.md` 已同步
- [ ] `docs/api/subscription-output-contract.md` 已同步
- [ ] `docs/deployment/lazycat-deployment.md` 已同步
- [ ] `docs/governance/changelog.md` 已更新（如本次发布需要）
- [ ] 文档中不包含本机绝对路径（如 `HOME/...` 或 `Users/<name>/...`）
- [ ] `docs/architecture/system-overview.md` 中模块路径与当前仓库一致

## 工程检查

- [ ] Node 24 baseline verified via `.nvmrc` and the Woodpecker `node-24` step
- [ ] `python scripts/run_docs_consistency_audit.py` 通过
- [ ] `bash scripts/test_smoke.sh` 通过
- [ ] `./.venv/bin/python -m pytest -q -x` 至少首个失败点已清零
- [ ] `./.venv/bin/python -m ruff check .` 通过
- [ ] 若本次发布由 PR 进入主线，PR current head 的必需检查已通过并已处理 actionable review feedback

## 安全检查

- [ ] `lzc-manifest.yml` 中 `SUB_TOKEN` / `DATA_ENCRYPTION_KEY` 为占位符
- [ ] 执行 `scripts/security_preflight.sh` 通过
- [ ] 解包 `.lpk` 不含 `.env`、`var/`、`*.db`、`*.pyc`、私钥文件
