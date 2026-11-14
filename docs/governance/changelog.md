# Changelog

## 1.0.13 - 2026-11-12

- 服务目录进页更快：分类列表、服务目录和自定义规则接口每个请求只读一次场景契约，查询次数不再随行数增长；悬停或聚焦导航里的「服务目录」时预取进页数据。
- 关着的对话框不再渲染正文，服务目录不再为隐藏的批量分配、置顶管理建整张表（此修复此前未进入分发包）。
- LPK 构建先用当前源码重建管理端，不再打包本地残留的旧前端产物。
- `/manage` 外壳带 `Cache-Control: no-cache`，部署后浏览器不会沿用引用旧分包的外壳；分包加载失败时「重试」整页重载。
- HTTP 接口字段、订阅输出和持久化数据不变，升级无需迁移。

## 1.0.12 - 2026-11-11

- 管理端换成「玻璃工作台」外壳：左栏下方由 WebGL 背景画出沙洲，选中项由水流勾勒；提供清透、烟熏两套主题和「自动 / 清透 / 烟熏」外观切换，选择会被记住。场景切换与管理菜单移到左栏顶部，去掉顶部标题栏。
- 配置与场景页改用主题变量，烟熏主题下不再出现白色控件和浅色卡片。
- 只改前端；HTTP 接口、订阅输出和持久化数据不变，升级无需迁移。

## 1.0.11 - 2026-10-04

- 所有持久化路由契约都可按所属场景编辑和删除；预置契约仅首次初始化，删除后不会随重启或恢复自动补回。
- 契约显式声明代理、直连或拒绝动作，三端输出按当前定义渲染；引用和默认去向需明确替代并原子迁移，缺失目标阻断订阅。
- 管理端显示删除引用和替代选择；策略备份 v2 包含完整契约定义、动作和视图，保留 v1 兼容并保护同步期间的新变更。

## 1.0.10 - 2026-10-04

- 完成按 LazyCat 用户隔离的工作区与首次初始化流程；数据库、密钥、缓存、设备订阅和备份路径独立，重启后公开订阅仍解析到原所属用户。旧根目录数据仅通过核实后的 `LEGACY_DATA_OWNER_ID` 显式绑定。
- 修复采集汇总，只统计本轮实际尝试与成功；混合节点导入保留有效节点并报告拒绝原因，警告重启后仍可见。
- 保留节点凭据、传输参数与来源身份；Clash / Surge / Shadowrocket 输出明确拒绝无法保留连接语义的节点，恢复两个旧查询 token 订阅入口。
- 字段加密在密钥错误或密文损坏时明确失败，故障局限于所属用户；策略恢复绑定已预览内容摘要，失败时完整回滚。
- 管理端完善来源、设备链接与预览、场景和策略操作，修复移动端溢出、复制反馈与焦点、弹窗可访问性；新建空场景可直接编辑 Profile。
- 分发包固定运行时镜像与离线二维码依赖；Alpine 3.21 digest 经开发机实际拉取与架构回读验证。部署参数通过受控 Secret 注入备份凭据；匿名健康检查仅展示实例状态。

## Unreleased

- 新增文档收口硬约束：
  - 新增 `docs/doc-sync-rules.json`，把高信号代码变更面映射到必同步文档
  - 新增 `scripts/check_doc_sync.py`，要求命中的规则必须通过 active plan 中的 `Documentation Impact` 以 `updated` 或 `docs-n/a` 收口
  - `docs-n/a` 正式限定为当前 diff 中唯一 active plan 的 repo-native 声明，不再接受散落说明
  - `.github/workflows/smoke.yml` 在 Ruff 后新增 `Doc sync` 校验步骤，并启用 `fetch-depth: 0`
  - 执行计划模板新增强制 `Documentation Impact` 区块与 `check_doc_sync.py` 验收命令
- 新增 docs CI：
  - 新增 `docs/governance/docs-check-config.json`，定义关键文档、索引覆盖、入口可发现性与路径一致性检查范围
  - 新增 `scripts/check_docs.py` 与 `check_docs_structure.py`、`check_docs_links.py`、`check_knowledge_index.py`、`check_docs_paths.py`
  - `.github/workflows/smoke.yml` 新增独立 `docs-checks` job，用标准库 Python 校验 knowledge health
- 新增 PR review feedback fetch：
  - 新增 `scripts/fetch_pr_feedback.py`，可从 GitHub 拉取 PR review threads、review comments 与 status checks
  - 新增 `docs/governance/pr-review-loop.md`，明确云端自动 review 与本地 feedback fetch 的职责边界
  - `docs/governance/git-workflow.md`、`AGENTS.md`、`CONTRIBUTING.md`、执行计划模板同步补充 PR review 回路
- 标准源兼容升级（AnyTLS/Hy2/TUIC）：
  - 拉取解析协议扩展为：`http/https/socks5/ss/trojan/vmess/vless/anytls/hysteria2(hy2)/tuic`
  - Clash 拉取改为多 UA 探测并择优（`ClashforWindows -> clash-verge -> mihomo`）
  - Shadowrocket 拉取支持 `[Proxy]` 与 Base64 URI 双格式自动识别
  - Surge `[Proxy]` 解析支持 `anytls/hysteria2/tuic` 扩展参数
  - 下发端 `clash.yaml` / `shadowrocket.conf` / `surge.conf` 新增 `anytls/hysteria2/tuic` 节点输出
  - 拉取 attempts 增加可观测字段：`request_variant`、`parsed_protocol_counts`、`skip_reasons`
  - `last_pull_error` 与管理页失败文案增强，区分网络失败与格式/协议失败
- 修复设备订阅在标准源场景被后台刷新误禁用的问题：
  - 无 GoRelay 设备发现时不再禁用现有设备订阅
  - 仅在无任何设备订阅时自动补齐 `Default` 设备
- 新增 Surge 全链路适配：
  - 新增设备订阅端点：`GET /sub/device/{token}/surge.conf`
  - 新增 Surge 一键导入链接（`surge:///install-config?...`）
  - 标准源新增 `surge_url` 字段，采集回退顺序调整为 `clash -> surge -> shadowrocket`
  - LazyCat Profile 新增 `surge_always_real_ip`、`surge_tun_excluded_routes`
  - 管理页与 legacy 页新增 Surge 状态、复制链接与一键导入入口
- 新增 v2 内部观测端点：`GET /readyz`、`GET /diagnostics`、`GET /metrics`
- 新增请求观测：`X-Request-Id` + JSON request log + Prometheus counter `lzctoclash_http_requests_total`
- 本地启动/停止脚本改为 instance + pidfile 作用域（替代 `pkill -f`）
- 高质量节点默认追加美国标识：
  - `高质量-高倍率` / `高质量-低倍率` 节点统一显示为 `🇺🇸 美国 · ...`
  - 适用于 GoRelay 与高质量机场拆分后的节点，并同步体现在 Clash / Shadowrocket / Surge 输出
  - 这是展示策略，不代表真实出口国家自动识别

## 0.3.1 - 2026-02-12

- 修复 Clash 导入 duplicate name：订阅生成阶段对节点名做稳定唯一化（同样应用于 Shadowrocket 输出）

## 0.3.0 - 2026-02-12

- 新增首次初始化门禁：
  - `GET /setup`
  - `GET /api/setup/status`
  - `POST /api/setup/init`
- 新安装未初始化实例仅放行 `/setup`、`/api/setup/*`、`/healthz`，其余业务路径返回 `503 setup required` 或跳转到 `/setup`
- 引入实例本地密钥存储：`/lzcapp/var/data/instance_secrets.json`（`0600`），分发包不再内置真实 `SUB_TOKEN` / `DATA_ENCRYPTION_KEY`
- 新增多用户隔离字段 `owner_user_id`，管理后台与订阅解析按 `lazycat_user_id` 进行数据隔离
- `GET /admin/accounts` 响应脱敏：移除明文敏感字段，改为 `has_*` 布尔标记
- 新增用户级 `SUB_TOKEN` 存储与解析，legacy 订阅按 token 仅返回所属用户数据
- 新增发布前安全门禁脚本：`scripts/security_preflight.sh`
- 构建流程净化：`lzc-build.yml` 排除 `__pycache__`、`*.pyc`、日志与临时文件
- 应用版本提升到 `0.3.0`

## 0.2.6 - 2026-02-12

- `lzc-manifest.yml` 新增 `application.public_path`（`/healthz`、`/sub/`、`/rules/`），确保订阅与探活可匿名访问，管理端仍走懒猫登录
- 新增懒猫身份头中间件：解析 `X-HC-*` / `X-LZC-*` / `X-LAZYCAT-*` 并写入 `request.state`
- 管理后台审计日志统一附加 `lazycat_user_id` 与 `client_ip`
- 管理页面顶部新增懒猫登录用户展示（有头时显示）
- 新增测试 `tests/test_lazycat_identity.py`，并补充管理页懒猫身份显示回归
- 应用版本提升到 `0.2.6`

## 0.2.5 - 2026-02-11

- 管理后台“全量刷新”改为管理员登录态一键执行（新增 `POST /admin/refresh`），移除 SUB_TOKEN 输入弹窗依赖
- 新增在线修改管理密码（新增 `PUT /admin/security/password`），校验旧密码并持久化保存
- 管理登录校验改为：持久化密码覆盖优先，`ADMIN_PASS` 作为回退
- 管理页顶部新增“返回用户页面”入口
- 用户页与管理页订阅原始链接支持“点击整行复制”并提供复制反馈

## 0.2.4 - 2026-02-11

- 新增“客服回复文本导入历史”持久化（按账号保存导入原文与统计）
- 管理端新增历史查询与删除接口：
  - `GET /admin/accounts/{account_id}/domain-import-histories`
  - `DELETE /admin/accounts/{account_id}/domain-import-histories/{history_id}`
- 删除历史支持“安全撤销绑定”：仅回滚仍未被后续修改的绑定项，并返回漂移跳过统计
- 管理页新增历史列表与“删除并撤销（安全模式）”入口

## 0.2.3 - 2026-02-11

- 修复本机端口错配导致的订阅链接 404：当 `APP_BASE_URL` 为本机地址且与当前请求端口不一致时，自动回退到请求基址
- 门户与管理页新增基址错配告警文案，便于定位“链接指向了别的本地服务”
- 修复 Clash 订阅下载在中文设备名场景下的响应头编码异常（`Content-Disposition` 文件名改为 ASCII 清洗策略）

## 0.2.2 - 2026-02-11

- 设备识别增强：支持 `设备名-「LVx」... 倍率` 语义截断，避免把入口名误识别为设备
- 自动对账并停用历史伪设备订阅 token（保留记录，不删除）
- `GET /admin/accounts/{id}/devices` 增加 `subscription_count`、`entry_count`、`is_stale`，并支持 `include_stale`
- `GET /admin/subscriptions` 增加 `include_disabled`
- 订阅链接基址解析新增 `LAZYCAT_APP_DOMAIN` 与 `X-Forwarded-*` 优先级，修复外网可用性
- 管理页/门户页增加本机地址告警与设备可读指标展示

## 0.2.1 - 2026-02-11

- 增加本地启动排障归档：`docs/operations/local-dev-runbook.md`
- 固化本地启动/停止脚本：`scripts/local_start.sh`、`scripts/local_stop.sh`
- `.env.example` 改为 shell-safe 默认（`APP_NAME` 加引号，`APP_BASE_URL` 默认留空）
- 后台入口视图增强：显示入口对应域名/IP、端口集合、使用设备
- 修复 GoRelay API 设备维度识别：设备名从规则名提取，不再误用入口组名

## 0.2.0 - 2026-02-10

- 引入多账号 GoRelay 采集与账号级快照
- 增加设备级订阅 token 与独立导入链接
- 增加域名待申请识别、客服回复导入、自动传播
- 新增管理接口：账号、设备凭证、快照、域名绑定
- 调整懒猫健康检查参数，降低冷启动误判
- 建立 `docs/` 专业文档体系

## 0.1.0 - 2026-02-10

- 初始版本：MCP 节点采集 + Clash/Shadowrocket 输出
