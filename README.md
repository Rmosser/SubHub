# SubHub

运行在懒猫微服上的订阅聚合服务，聚合来源与分流规则，生成可持续更新的设备级订阅。
配置分工与批准边界见 [core beliefs](docs/design-docs/core-beliefs.md)。

## 核心能力

- 多 GoRelay 账号并行采集，按用户隔离
- 设备级订阅发布，每账号每设备独立 token
- Clash / Shadowrocket / Surge 三输出
- AI / GFW 规则聚合、缓存降级与审计提示
- 管理端快照、诊断、离线审核包与策略恢复

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
