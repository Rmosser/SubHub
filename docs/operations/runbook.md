# Operations Runbook

适用场景：运行中的 SubHub 服务运维与发布前操作。

接任务、分支、本地验证与 PR 协作入口见 `CONTRIBUTING.md`；可执行质量命令见 `docs/quality.md`。

## 日常检查

1. 打开 `/healthz`，确认 `ok=true`、`setup_required` 与 `access_mode`。公开健康检查不返回用户数据。
2. 登录管理台，查看“高级 → 系统状态”或 `/api/status`：
   - 最近一次刷新时间与 `last_error`
   - 各来源本次拉取结果、待申请入口数量与快照节点数
   - 当前场景下的设备与节点池
3. 新用户通过 `/setup` 创建工作区；已有根目录数据的升级归属按部署文档配置 `LEGACY_DATA_OWNER_ID`。

## 常用操作

### 立即刷新规则与采集

```bash
curl -X POST -H "X-HC-User-ID: <当前懒猫用户 ID>" "http://127.0.0.1:8000/api/refresh"
```

以上命令仅用于受控本机入口。经懒猫公网入口调用时使用当前用户的网关登录态，由网关注入身份，订阅 token 不用于管理鉴权。

### 单账号采集

在管理台触发：`POST /api/gorelay/accounts/{id}/crawl`

### 导出离线审核包

```bash
curl -L -H "X-HC-User-ID: <当前懒猫用户 ID>" "http://127.0.0.1:8000/api/devices/<TOKEN>/export/clash-bundle.zip?scenario_id=scenario-default" -o review.zip
```

审核时先看：

1. `AUDIT.md`
2. `clash.yaml`
3. `providers/*.yaml`

### AI 工作流安全执行

- Web：`/manage` -> `LLM 工作流`，按 `直连审核 -> 分类分流 -> 目录分组` 顺序操作
- CLI：先 `preview patch`，确认 diff 后再 `apply patch`

```bash
./.venv/bin/python -m app.cli.main preview patch patch.json
./.venv/bin/python -m app.cli.main apply patch patch.json
```

### 立即同步自有策略备份

在管理台“高级 -> 策略备份”点击“立即同步”，确认：

- `last_result=ok`
- `last_commit_sha` 已更新

若失败，读取同一项的 `last_sync_run_id` 和 `last_error_detail`，按
`phase` 区分导出、Git 同步或状态落盘；detail 中的消息和堆栈已脱敏，
保留 `dirty=true` 时不要清除待同步状态。
- GitHub 私有仓库出现新的策略资产 diff
- 自动备份提交显式关闭交互式 Git 签名，不依赖开发机的全局 GPG/SSH 签名程序。
- 加密凭据不能解密时会报告错误；保留数据库并恢复对应工作区原来的 `data/field_cipher.key`，不要替换为随机新密钥。

### 本地 SQLite 恢复演练

恢复能力的验收必须包含空白目标语义 readback，以及独立子进程在
promotion sidecar 清理前后收到 `SIGKILL` 的场景；启动时必须消费 durable
promotion journal 并语义 readback；只看到备份文件或 `integrity_check`
通过都不算恢复成功。仓库内演练只使用 pytest 临时目录和 fake Git/fake alert，
不会连接生产仓库、发送真实告警或读取真实 Secret；告警演练使用 fake
HTTPS transport 并核对稳定 `Idempotency-Key`；启动重试也必须验证全局
deadline 不会随 receipt 数量线性阻塞，未处理 receipt 留在 durable outbox：

告警接收端必须是最终 HTTPS URL；客户端会 fail-closed 拒绝重定向，避免
urllib 将 POST 改写为 GET 或丢失 body/idempotency headers。

```bash
./.venv/bin/python -m pytest tests/test_runtime_recovery.py -q
```

演练会检查 dirty generation 重启恢复、外部 push 歧义 compare/reconcile、
backup 到独立目标的策略语义，以及 kill 后新进程对手动分类和自定义规则的
实际读回。

### 预览 / 应用策略恢复

1. 在“恢复来源”输入分支引用或 commit SHA
2. 点击“恢复预览”，确认变化摘要
3. 确认无误后点击“应用恢复”
4. 抽查：
   - 手动分类
   - 全局 / 场景自定义规则
   - 场景 pin groups 与 catalog bindings

### 懒猫双路出站

- GoRelay 采集默认依赖 `HTTP_PROXY/HTTPS_PROXY`
- 标准源的 `direct_only` 必须保持真直连
- 若本地成功、懒猫失败，先对比 `pull_network_mode` 与 `config_fingerprint`
- 本地成功配置优先通过“复制配置 JSON / 从配置 JSON 导入”同步到懒猫实例
- 盒子侧桥接安装与验证见 `docs/operations/lazycat-egress-bridge.md`

### 客服域名回复导入

在管理台“域名导入”区域粘贴客服回复文本并提交。

## 发布前检查

1. 至少一个账号采集成功
2. 至少一个设备订阅可下载
3. `shadowrocket.conf`、`clash.yaml`、`surge.conf` 都可生成
4. `last_error` 为空或仅为已知可接受警告
5. `scripts/security_preflight.sh` 通过

## 契约迁移、删除与策略恢复

在路由契约页编辑当前定义，删除前查看受影响的场景和引用数量。需要迁移时明确选择替代契约，提交会原子替换引用和默认去向后删除旧记录。全局删除在默认场景进行；场景私有契约在 owner 场景进行。删除后重启不会恢复模板。

无契约或无默认项是有效草稿，订阅生成会阻止交付并指出缺项。创建新契约后明确设为默认，再生成订阅。

策略备份 `subhub.policy-backup.v2` 包含完整契约定义、动作和场景视图，恢复会移除备份不存在的定义，包括预置模板。旧 v1 备份缺少预置定义，按显式旧版恢复兼容处理。标准源配置不属于策略备份；若恢复会移除、禁用或把源所引用的契约改为不可接收节点的动作/拓扑，先重新绑定源再恢复。恢复失败会回滚所有策略写入。升级前保存策略备份和数据库快照；回滚包与数据库需成对操作。

完整恢复的范围是备份拥有的策略状态。现存场景配置与设备、标准源等运行数据保留；未出现在备份中的场景不会被删除，其旧私有契约及契约视图会清空。快照在数据库事务内统一读取；同步期间的新修改仍保持待同步状态。
