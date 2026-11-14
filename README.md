# SubHub

识别网络连通、隐私泄漏和未授权链路，并据此分流或阻断的自托管工具，运行在懒猫微服上。
配置分工与批准边界见 [core beliefs](docs/design-docs/core-beliefs.md)。

## 工作方式

1. **识别连通**：探测容器出口、代理桥与订阅来源的可达性，给出诊断、修复提示与主动告警。
2. **识别泄漏与未授权链路**：导入 Surge / Clash / Shadowrocket 的连接日志，按域名归并证据，找出未归类、走错出口或不该出现的连接。
3. **分流与阻断**：把识别结果落成规则分类与路由合约（直连 / 代理 / 拒绝），先预览差异再应用，生成每台设备独立、可持续更新的客户端配置。

## 核心能力

- 出口与来源诊断：代理桥探测、来源拉取诊断、运行心跳与告警
- 连接日志分流工作流：会话式导入日志、候选清单、补丁预览与应用
- 规则分类与路由合约：直连 / 代理 / 拒绝，AI / GFW 规则聚合与缓存降级
- 设备级配置发布：Surge / Shadowrocket / Mihomo（Clash Mi）三端输出，每设备独立 token
- 诊断脱敏：订阅地址中的密钥在诊断与状态读取中隐藏
- 多用户隔离、快照、离线审核包与策略恢复

## 快速入口

- 门户页：`GET /`
- 管理控制台：`GET /manage`
- 首次初始化门禁：`GET /setup`
- 健康检查：`GET /healthz`

## 访问与初始化边界

- 默认受懒猫登录保护：`/`、`/manage`、`/setup` 及其他未列入白名单路径
- 匿名放行：`/healthz`、`/sub/*`、`/rules/*`
- 尚未初始化的用户：
  - `/manage` 引导进入 `/setup`
  - 登录后点击“创建工作区”，生成独立密钥、数据库和首个设备订阅
  - `/api/*` 在完成初始化前返回 `409 setup required`
- 实例尚无已初始化用户时，`/sub/*`、`/rules/*` 返回 `503 setup required`；`/healthz` 返回 `setup_required=true`
- `MANAGE_API_REQUIRE_LOGIN=true` 按懒猫用户隔离来源、规则、场景、设备和缓存；公开订阅凭 token/public ID 解析所属工作区
- 旧版本根目录数据需要运维通过 `LEGACY_DATA_OWNER_ID` 明确指定归属。新登录用户不会自动继承旧数据；升级前请读 `docs/deployment/lazycat-deployment.md`
- 本地 `MANAGE_API_REQUIRE_LOGIN=false` 为单用户开发模式，使用一份共享工作区

## 语言

- 管理台与旧 GoRelay 页支持 `zh-CN` / `en-US`
- 语言优先级：`subhub_lang` cookie -> `Accept-Language` -> `zh-CN`
- 仅用户可见说明文本随语言变化；机器字段与结构保持稳定

## 本地开发

Node baseline 见 `.nvmrc`；使用 `nvm` 时先执行 `nvm install 24 && nvm use`。

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
bash scripts/local_start.sh
```

停止服务：

```bash
bash scripts/local_stop.sh
```

最小检查：

```bash
node -v
./.venv/bin/python -m ruff check .
bash scripts/test_smoke.sh
npm ci --prefix frontend
npm run test:unit --prefix frontend
npm run build --prefix frontend
npm run lint --prefix frontend
```

前端单元测试覆盖外部 API 响应的运行时契约；CI 会在 Node 步骤中运行测试、TypeScript/Vite build 和 lint。

完整质量命令见 `docs/quality.md`；本地启动问题见 `docs/operations/local-dev-runbook.md`。

## 懒猫部署

```bash
bash scripts/deploy_to_lazycat.sh --deploy --box <box-name> --confirm
lzc-cli app status cloud.lazycat.subhub
scripts/security_preflight.sh
```

不带 `--deploy` 的脚本调用只构建并保留 LPK；真实安装必须明确指定批准的盒子和
`--confirm`，并在安装、健康检查与版本/digest readback 通过前保留旧构建产物。

部署步骤与验证见 `docs/deployment/lazycat-deployment.md`；运行期问题见 `docs/operations/troubleshooting.md`。

## 文档入口

- Context Map：`docs/index.md`
- 配置原则：`docs/design-docs/core-beliefs.md`
- 架构：`docs/architecture/system-overview.md`
- API 契约：`docs/api/http-api.md`
- 订阅输出契约：`docs/api/subscription-output-contract.md`
- 质量与验证：`docs/quality.md`
- 运维：`docs/operations/runbook.md`
- 故障排查：`docs/operations/troubleshooting.md`
- 本地开发：`docs/operations/local-dev-runbook.md`
- 部署：`docs/deployment/lazycat-deployment.md`
- 发布检查：`docs/governance/release-checklist.md`
- 协作规范：`CONTRIBUTING.md`

## 许可证

[GNU AGPL-3.0](LICENSE)
