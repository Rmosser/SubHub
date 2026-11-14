# HTTP API

## Public

订阅输出的统一契约表见：`docs/api/subscription-output-contract.md`

管理 UI 的当前主入口是 `GET /manage`。
`GET /setup` 在当前用户处于 `setup_required=true` 时作为初始化门禁出现，不应被当作日常管理入口。

- `GET /`
- `GET /manage`
  - `/manage` 与 `/manage/*` 都返回前端外壳，带 `Cache-Control: no-cache`，浏览器每次都要重新验证，部署后不会沿用引用旧分包的外壳；`/manage/assets/*` 是带哈希的静态文件。
- `GET /sub/device/{token}/clash.yaml`
- `GET /sub/device/{token}/clash/providers/{provider_key}.yaml`
- `GET /sub/device/{token}/clash/rules/{asset_key}.list`
- `GET /sub/device/{token}/shadowrocket-nodes.txt`
- `GET /sub/device/{token}/shadowrocket.conf`
- `GET /sub/device/{token}/shadowrocket-legacy.conf`（`308` 到 `shadowrocket.conf`，不再渲染独立配置）
- `GET /sub/device/{token}/surge.conf`
- `GET /sub/clash.yaml?token=...` (legacy)
- `GET /sub/shadowrocket.conf?token=...` (legacy)
- `GET /setup`
- `GET /api/setup/status`
- `POST /api/setup/init`

### 身份、工作区与初始化

- `MANAGE_API_REQUIRE_LOGIN=true` 时，管理请求从懒猫网关身份解析用户，所有数据与后台服务使用该用户的独立工作区。
- `GET /api/setup/status` 要求登录，返回当前用户的 `setup_required` / `initialized`、实例级 `instance_initialized`、`access_mode`、`storage_status` 和 `recovery_hint`；不返回其他用户或设备凭据。
- `POST /api/setup/init` 为当前登录用户创建工作区，返回 `ok`、`initialized`、`setup_required`、`device_token` 和 `device_public_id`；重复请求保持既有设备身份。
- `/setup` 提供初始化页面，已初始化用户重定向到 `/manage`；`/manage` 保持可打开，并在页面内引导尚未初始化的用户。
- 未登录的管理/API初始化请求返回 `401 lazycat login required`；已登录但未初始化的管理请求返回 `409 setup required`。
- 实例没有已登记用户时，`/sub/*`、`/rules/*` 返回 `503 setup required`。初始化后，公开订阅按 token/public ID 查找所属工作区，与访问者的登录身份无关；未知或冲突标识拒绝访问。
- `/healthz` 保持匿名 `200`，仅返回实例级状态、时间、`setup_required` 与 `access_mode`；账户、来源、代理和缓存详情通过当前用户的 `/api/status` 或 `/diagnostics` 查看。
- `MANAGE_API_REQUIRE_LOGIN=false` 是显式单用户开发模式，不宣称多用户隔离。
- 旧根目录数据仅能由运维设置 `LEGACY_DATA_OWNER_ID` 绑定。新用户初始化不会领取旧凭据；既有归属持久化后不能通过改环境变量重新分配。
- 已登记工作区的数据库丢失、密钥损坏或密文无法解密时，该用户请求返回 `503` 并提示恢复原数据库和 `field_cipher.key`。其他工作区仍可使用；修复存储后可重试，不把密文当成明文凭据使用。

旧查询参数入口 `/sub/clash.yaml?token=...` 与 `/sub/shadowrocket.conf?token=...` 委托到默认场景的 canonical 渲染路径。历史 `/admin/*`、`/rules/ai.list`、`/rules/gfw.list` 不属于当前实现的 API；管理使用 `/api/gorelay/*`，规则资产使用设备订阅生成的 URL。

`GET /sub/device/{token}/clash.yaml` / `GET /sub/clash.yaml` 额外约定：

- 响应 `Content-Type` 为 `application/x-yaml`
- 响应头包含 `Content-Disposition`（文件名已做 ASCII 清洗，避免编码异常）
- 响应头包含 `Profile-Update-Interval: 1800`
- Clash 主配置默认使用 `proxy-providers`，节点不再内联到主配置
- 固定 5 个 provider key：`high-premium` / `high-standard` / `medium` / `bulk` / `chain-home`
- 当 Clash 命中被引用的空合同/空主池时，返回 `409 clash-build-blocked`

`GET /sub/device/{token}/clash/providers/{provider_key}.yaml` 额外约定：

- 响应 `Content-Type` 为 `application/x-yaml`
- 返回顶层 `proxies:` 列表，仅包含对应质量池节点
- `provider_key` 仅允许：`high-premium` / `high-standard` / `medium` / `bulk` / `chain-home`
- 非法值：返回 `404 invalid clash provider key`

`GET /sub/device/{token}/clash/rules/{asset_key}.list`（含显式场景路径）返回 `text/plain` classical 规则集；未知资产返回 `404`。集合行只包含匹配条件和已有的 `no-resolve` / `src` / `extended-matching`，策略由主配置引用指定。Surge rule-set 资产采用相同的无策略格式。

proxy-provider / rule-provider 由 URL 的设备身份、场景与资产路径定位；显式场景签名 URL 按既有 `exp` / `sig` 验证，不依赖 User-Agent。`clash.meta/1.19.32`、`clash.meta/v1.19.33`、`Go-http-client/1.1` 与空 UA 均可拉取；UA 不会绕过 token 或签名校验。

`GET /sub/device/{token}/clash.yaml` / `GET /sub/device/{token}/shadowrocket.conf` / `GET /sub/device/{token}/surge.conf` 统一约定：

- 公开订阅入口不再暴露 `profile` / `flavor` 维度；订阅内容始终跟当前场景 settings/profile 走
- 管理端复制链接统一指向显式场景路径 `/sub/device/{token}/{scenario_slug}/...`
- 默认路径 `/sub/device/{token}/...` 仅作为默认场景别名存在
- 若请求仍携带 `profile` 或 `flavor` 查询参数，返回 `400 profile/flavor query parameters are no longer supported`
- 当前 canonical 输出沿用原 LazyCat 主线：
  - Clash 注入：
    - `mixed-port`: `7890`
    - `dns.enable`: `true`
    - `dns.listen`: `127.0.0.1:1053`
    - `dns.enhanced-mode`: `redir-host`
    - `dns.use-hosts`: `true`
    - `dns.default-nameserver`: `223.5.5.5` / `119.29.29.29`
    - `dns.nameserver`: `https://doh.pub/dns-query` / `https://dns.alidns.com/dns-query`
    - `dns.fallback`: `tls://1.1.1.1` / `tls://8.8.4.4`
    - `dns.respect-rules`: `true`
    - `dns.proxy-server-nameserver`: `223.5.5.5` / `119.29.29.29`
  - Shadowrocket 注入（best-effort）：
    - `[General] always-real-ip = *.heiyu.space,*.lazycat.cloud,*.lazycatmicroserver.com`
    - `[General] tun-excluded-routes = 6.6.6.6/32,2000::6666/128`
  - Surge 注入（best-effort）：
    - `[General] always-real-ip = *.heiyu.space,*.lazycat.cloud,*.lazycatmicroserver.com`
    - `[General] tun-excluded-routes = 6.6.6.6/32,2000::6666/128`
  - 语义说明：
    - Mihomo 默认主线已收敛为 `redir-host + respect-rules + use-hosts`
    - `dns.fake-ip-filter` / `tun` / `sniffer` 仍支持，但只在显式开启对应高级模式时输出
    - `Host Records` 只作为高级覆盖/调试兜底：Surge/Shadowrocket 渲染到 `[Host]`，Mihomo 渲染到顶层 `hosts`

`GET /sub/device/{token}/shadowrocket-nodes.txt` 额外约定：

- 响应 `Content-Type` 为 `text/plain`
- 响应头包含 `Content-Disposition`
- 响应头包含 `Profile-Update-Interval: 1800`
- 响应体为 BASE64 编码后的叶子节点分享链接纯文本，一行一个 URI
- 不包含链式组合节点；链式家宽仅存在于 `shadowrocket.conf` 的内联 `[Proxy]`
- 仅当当前 token 下导出的节点可靠地对应到单一 GoRelay 账号且该账号 quota 可用时，响应头附 `subscription-userinfo`

`GET /sub/device/{token}/shadowrocket.conf` 额外约定：

- 当前实现保留内联 `[Proxy] + [Proxy Group] + [Rule]`
- 订阅主机 DIRECT 仅为拒绝类 `FINAL`（平台原生拒绝目标或 `routing_action=reject` 的契约）的兜底：排在所有用户和系统规则之后、紧挨 FINAL 之前；已有 DOMAIN / DOMAIN-SUFFIX 或覆盖 IP 字面量的目标 IP-CIDR / IP-CIDR6 规则时不补，保留其原位置与策略（包括 LazyCat 系统直连）。最终策略为 DIRECT 或代理时不补。规则作用于该主机所有端口和路径，包括非 `/sub/` 请求；新增单地址 IP 规则显式带 `no-resolve`，其余解析语义不变
- 显式拒绝订阅主机时，配置注释及管理侧结构化诊断共用 `shadowrocket-subscription-host-rejected` warning，说明“Shadowrocket 连接时无法更新这份配置”，提示改为可用代理或 DIRECT、或断开 VPN 后更新；此后果以实际命中该规则为前提。静态检测仅覆盖上述确定条件，不解析 DNS，也不推断关键字、GEOIP、规则集及逻辑/端口等写法；这些规则仍可在兜底之前命中
- 显式远程 RULE-SET / DOMAIN-SET 继续保留，需保证断开时可解析、连接时按规则可达；服务端不输出 `update-url`，由客户端保存下载地址
- 默认仅保留被入口组或链式节点实际引用的自动代理组；未引用的 `·故障转移` / `·手动` 辅助组不再输出
- 链式家宽节点按唯一后置家宽出口生成，不按“前置入口 × 后置出口”展开
- 链式节点通过 `forwarding-proxy=链式入口·自动` 走显式链式入口组
- `链式入口·自动` 的成员来自中等质量 / 低质量大流量池的自动组
- 当启用 Shadowrocket HTTP 管线设置时，主订阅可额外包含 `[URL Rewrite]`、`[Script]`、`[MITM]`
- `[MITM]` 当前会显式输出 `enable = true`
- Shadowrocket 2.2.93 已验证显式 `host:8443` MITM；禁止 `hostname = *`。须安装 CA、开启系统完全信任并启用 HTTPS 解密、保存、重启 VPN
- Shadowrocket 2.2.93 下载后直接激活 Rewrite，无需额外保存
- Map Local 存储值保留但不再下发；配置注释及管理诊断告警，响应 mock 使用 `[Script]`

`GET /sub/device/{token}/shadowrocket-legacy.conf` 及场景级同名路径只返回 `308 Permanent Redirect` 到对应的 `shadowrocket.conf`。管理 API 不再发放 legacy URL，服务端也不再保留独立 legacy renderer。

`GET /api/settings/lazycat-profile` / `PUT /api/settings/lazycat-profile`：

- 用于查看/更新默认 LazyCat DNS/TUN 注入配置
- 配置项：
  - `clash_fake_ip_filter`（list[string]）
  - `clash_always_real_ip`（list[string]）
  - `clash_dns_enable`（bool）
  - `clash_dns_listen`（string）
  - `clash_dns_enhanced_mode`（string）
  - `clash_dns_use_hosts`（bool）
  - `clash_mixed_port`（int, 1-65535）
  - `clash_udp_default_enabled`（bool）
  - `clash_dns_default_nameserver`（list[string]）
  - `clash_dns_nameserver`（list[string]）
  - `clash_dns_fallback`（list[string]）
  - `clash_tun_enable`（bool）
  - `clash_tun_stack`（string）
  - `clash_tun_auto_route`（bool）
  - `clash_tun_auto_detect_interface`（bool）
  - `clash_tun_dns_hijack`（list[string]）
  - `clash_tun_strict_route`（bool）
  - `tun_excluded_routes`（list[string]）
  - `shadowrocket_always_real_ip`（list[string]）
  - `shadowrocket_tun_excluded_routes`（list[string]）
  - `shadowrocket_url_rewrite`（list[string]）
  - `shadowrocket_mitm_hostname`（list[string]）
  - `shadowrocket_map_local`（list[string]）
  - `shadowrocket_script_request`（list[string]）
  - `shadowrocket_script_response`（list[string]）
  - `surge_always_real_ip`（list[string]）
  - `surge_tun_excluded_routes`（list[string]）
  - `surge_block_quic`（string）
  - `surge_http_api`（string）
  - `surge_http_api_secret`（string）
  - `surge_http_api_tls`（bool）
  - `surge_http_api_web_dashboard`（bool）
  - `surge_mitm_h2`（bool）
  - `surge_mitm_tcp_connection`（bool）

`GET /api/profile-capabilities`：

- 用于管理台能力矩阵与专家模式动态渲染
- 返回：
  - `groups`：能力分组
  - `clients`：客户端顺序（`surge` / `clash` / `shadowrocket`）
  - `expert_field_keys`：未被能力矩阵覆盖、仍需在专家模式直接编辑的设置 key
- `groups[].capabilities[].subfields[].clients.*.editing_mode`：
  - `shared`：共享编辑项；矩阵中显示为“已共享编辑”
  - `standalone`：单独编辑项；只影响当前客户端自己的设置 key
  - `experimental`：实验性单独编辑项；行为与 `standalone` 相同，但字段级能力仍待验证
  - `adapted`：目标客户端没有原生字段，但会从共享 truth 稳定投影生成
  - `unavailable`：该客户端没有等价能力或当前没有可写原生 key
- 当前已确认：`Shadowrocket skip-proxy` 返回 `support.status=supported` 与 `editing_mode=shared`；`Mihomo skip-proxy` 返回 `editing_mode=adapted`
- 当前已确认：`Control API Access` family 里，`Mihomo external-controller / secret` 与 `Surge http-api / http-api-secret` 走共享 truth
- 当前已确认：Surge 额外原生字段 `block-quic`、`http-api-tls`、`http-api-web-dashboard`、`[MITM] h2`、`[MITM] tcp-connection` 已进入能力矩阵
- 当前 HTTP 管线口径：
  - `Shadowrocket URL Rewrite`：`support.status=supported`；2.2.93 下载后直接激活
  - `Shadowrocket MITM Hostname`：`support.status=supported`，显式 `host:8443` 也已验证，须安装并完全信任证书
  - `Shadowrocket Map Local`：`support.status=downgraded`，设置保留但不再下发，并返回告警
    - 编辑器 Map Local 与 Script 卡片同步说明已保存的 Map Local 条目不下发，推荐响应 Script，不再推荐 Map Local 回退；能力状态、诊断代码与可编辑字段保持不变
  - `Shadowrocket Script`：请求/响应脚本均为 `support.status=supported` 与 `editing_mode=standalone`
- `groups[].capabilities[].subfields[].clients.*.options`：
  - 可选字段，仅在枚举型可编辑项上返回
  - 每个 option 包含：
    - `value`
    - `label` / `label_i18n`
    - `description` / `description_i18n`
  - 当前已用于 Mihomo / Surge 的日志级别下拉

`PUT /api/general-profile` / `POST /api/general-profiles` / `PUT /api/general-profiles/{id}`：

- 当通过 `settings` 或 `capabilities` 提交非法枚举值时返回 `400`
- 管理台主矩阵当前默认通过 `settings` 提交保存，以保留跨客户端的单独编辑值
- `POST /api/scenarios` 创建未携带旧配置的空场景时，默认使用可直接编辑的现代卡片状态。显式旧 `settings` 及已有场景保持兼容，不自动重置配置。
- `capabilities` 写法继续兼容历史共享链路，但不应用于新的单独编辑字段
- 共享 family 在保存时会执行单一真相收敛：
  - `excluded-routes`：`tun_excluded_routes` / `surge_tun_excluded_routes` / `shadowrocket_tun_excluded_routes` 强同步
  - `control-api-access`：`clash_external_controller` / `surge_http_api` 与 `clash_secret` / `surge_http_api_secret` 强同步
  - `skip-proxy`：只保留域名 / 主机 truth 到 `surge_skip_proxy` / `shadowrocket_skip_proxy`；IP/CIDR 条目会迁入 `excluded-routes`
- 当前已校验字段：
  - `clash_log_level`：`silent` / `error` / `warning` / `info` / `debug`
  - `surge_loglevel`：`notify` / `warning` / `info` / `verbose`
- 历史未知值仍可通过读取接口返回，但不能作为新写入值再次提交

`POST /api/profile-imports/shadowrocket/preview`：

- 用于把成熟 Shadowrocket `.conf` 里的全局运行项预解析成 SubHub Profile 可写真相
- 请求体：
  - `text`：Shadowrocket 配置全文
  - `current_settings`：当前场景 settings，用于生成 `diff_to_current`
  - `selected_template_settings`：当前选中模板 settings，用于生成 `diff_to_selected_template`
- 返回：
  - `ok`
  - `mapped_settings`：当前 v1 已成功吸收到 SubHub canonical profile 的字段
  - `warnings`：高风险项与降级说明；包含 `MITM / Script / URL Rewrite` 复核提示
  - `unsupported_items`：当前产品还没有稳定 canonical mapping 的字段，例如 `bypass-system`、`dns-server`
  - `ignored_sections`：明确不进入 v1 的 section 或字段，例如 `[Proxy]`、`[Proxy Group]`、`[Rule]`、`update-url`
  - `diff_to_current`
  - `diff_to_selected_template`
  - `errors`：空文本、非法 section、重复 key、无效 Host Records 等结构化错误
- 当前 v1 导入范围：
  - `[General] ipv6` → `surge_ipv6` family shared truth
  - `[General] skip-proxy` → `surge_skip_proxy`；其中 IP / CIDR 自动拆入 `tun_excluded_routes`
  - `[General] tun-excluded-routes` → `tun_excluded_routes`
  - `[General] always-real-ip` → `shadowrocket_always_real_ip`
  - `[Host]` → `shadowrocket_host_records`
  - `[URL Rewrite]` → `shadowrocket_url_rewrite`
  - `[Script]` → `shadowrocket_script_request` / `shadowrocket_script_response`
  - `[MITM] hostname` → `shadowrocket_mitm_hostname`

`GET /api/devices`：

- 可选参数：`scenario_id`，默认 `scenario-default`
- 返回当前场景解析后的设备订阅链接
- 每个设备项只包含单一 `links`，不再返回 `scenario_links` 全量矩阵
- 每个设备项会携带当前解析场景的 `scenario_id` / `scenario_slug` / `scenario_name`
- `links` 只包含 canonical URL / scheme，不再返回 `*_lazycat_*` / `*_raw_*` 变体

`GET /api/devices/{token}/preview-summary` / `GET /api/devices/{token}/preview-content` / `GET /api/devices/{token}/render-preview`：

- 存量不可表示规则也经过目标平台校验。UID 因当前没有可信目标 OS 不下发，原库记录保留；三端管理预览的 warnings 返回 `*-rule-unsupported`、`refused` 分类与迁移提示，Clash 离线包 AUDIT 同样包含被拒原因。规则省略可能改变后续匹配，须审核迁移提示。

- Shadowrocket 的订阅主机拒绝告警通过同一次构建返回：`preview-summary.summary.warnings` / `summary.diagnostics.downgraded`、`render-preview.warnings` / `diagnostics.downgraded`，以及因其他 blocker 返回 `409` 时的 `detail.warnings`（包括 `preview-content` 和公开主配置端点）。稳定代码为 `shadowrocket-subscription-host-rejected`，`severity=warning`、`bucket=downgraded`，自身不产生 blocker 或额外 409。渲染与诊断使用相同的实际托管订阅 URL；管理界面直接展示结构化 message，无需解析注释。
- 拒绝判断依据解析后的目标：复用平台原生目标分类（Shadowrocket 支持的原生拒绝目标见订阅输出契约），或契约 `routing_action=reject`；最终策略优先读取 IR 的默认契约动作。用户契约、策略组的名称及 `REJECT-` 前缀不赋予拒绝语义，例如 `REJECT-office` 代理契约仍为代理。

- 必选参数：`target=surge|clash|shadowrocket`
- 可选参数：`scenario_id`，默认 `scenario-default`
- 不再接受 `profile` / `flavor` 查询参数；若仍传入，返回 `400 profile/flavor query parameters are no longer supported`
- 渲染结果始终跟当前场景 settings/profile 走

`GET /api/devices/{token}/export/clash-bundle.zip`：

- 受管理端登录保护，不走匿名 `/sub/*`
- 不再接受 `profile` / `flavor` 查询参数；导出内容始终跟当前场景 settings/profile 走
- 可选参数：`scenario_id`
- 响应 `Content-Type` 为 `application/zip`
- 压缩包固定包含：`clash.yaml`、`providers/*.yaml`、`manifest.json`、`README.txt`、`AUDIT.md`
- 离线 zip 会剥离 `render-warnings`
- 当 Clash 存在 blocker 时返回 `409 clash-build-blocked`
- `AUDIT.md` 汇总自动组或 provider 任一层的测速覆盖、两层有效测速且规范化 HTTP(S) URL 不同的重复组（E-M-019、LINT-MHM-207）、缺少 `empty-fallback` 的潜在空组，以及 residual CIDR overlap 计数；同 URL 或无法静态确定的组合不报告重复
- blocked detail 的 `provider_health` 增加 `use_groups_with_duplicate_health_check` 和 `groups_without_empty_fallback` 名称列表；前者仅列两层有效测速且规范化 URL 不同的组，同 URL（即使 interval 不同）、无效 URL 和无法静态确定的组合不列入。URL 比较统一首尾空白、scheme/主机大小写、默认端口、空路径，忽略 fragment，保留路径大小写与 query。后者非空时增加 `clash-use-group-empty-fallback-missing` error blocker（沿用 `409 clash-build-blocked`），重复测速仅报告。默认保留组级测速且不输出 provider health-check
- 审核入口以离线 zip 为准，不要把在线订阅文本与离线包混审

## Management API (`/api/*`)

说明：

- 这些接口用于 `/manage` 管理页面与 CLI。
- 是否要求懒猫登录身份由 `MANAGE_API_REQUIRE_LOGIN` 控制（开发环境通常关闭）。
- 管理台页面语言由 `subhub_lang` cookie 优先，其次 `Accept-Language`；当前仅支持 `zh-CN` / `en-US`。
- API 请求若带 `Accept-Language: en-US`，仅直接展示给用户的人类说明字段会切英文；机器字段名、结构、枚举值与订阅产物命名保持不变。

### Sources

- `GET /api/sources/gorelay`
- `POST /api/sources/gorelay`
- `PUT /api/sources/gorelay/{source_id}`
- `DELETE /api/sources/gorelay/{source_id}`
- `GET /api/sources/standard`
- `POST /api/sources/standard`
- `PUT /api/sources/standard/{source_id}`
- `DELETE /api/sources/standard/{source_id}`
- `POST /api/sources/standard/{source_id}/pull`
- `POST /api/sources/standard/{source_id}/qr/{field}`
- `GET /api/sources/standard/{source_id}/qr/{field}`
- `DELETE /api/sources/standard/{source_id}/qr/{field}`
- `GET /api/sources/standard/{source_id}/qr/{field}/image`
- `POST /api/gorelay/accounts/{account_id}/crawl`

标准源 `ingest_kind`：

- `remote_subscription`：远程订阅源（默认）
- `manual_nodes`：自建节点源，手动粘贴叶子节点 URI

标准源 `quality_group` 允许值：

- `中等质量`
- `低质量大流量`
- `高质量机场`

标准源订阅字段说明：

- 通用字段：
  - `name`（必填）
  - `target_contract_id`（`route_contract` 模式下必填，必须引用启用中的 route contract）
  - `source_mode`（`route_contract|high_quality_airport`）
  - `ingest_kind`（可选，默认 `remote_subscription`）
  - `enabled`
- `remote_subscription` 字段：
  - `clash_url`（必填）
  - `shadowrocket_url`（必填）
  - `surge_url`（可选，默认空；采集回退顺序为 `clash -> surge -> shadowrocket`）
  - `pull_network_mode`（可选，默认 `direct_then_proxy`）
  - `direct_then_proxy`：直连优先，失败后再尝试环境代理
  - `direct_only`：仅直连
  - `proxy_then_direct`：代理优先，失败后再尝试直连
- `manual_nodes` 字段：
  - `manual_nodes_text`（必填）
  - 多行纯文本，一行一个叶子节点 URI（如 `ss://` / `trojan://` / `vmess://` / `vless://`）
  - 不要求 `clash_url` / `shadowrocket_url` / `surge_url`
  - `v1` 只支持 `route_contract`，不接受 `high_quality_airport` 自动拆分
- `route_contract` 模式必须显式提供 `target_contract_id`（更新时也必须继续提供可验证的既有绑定）；`quality_group` 仅作为已记录旧数据的迁移别名。省略 target、显式未知 target、非法 mode 或不匹配的 quality group 均返回 `400`，不会静默改写到 `medium` / `route_contract`。
- `high_quality_airport` 模式不接受 `target_contract_id`；更新标准源时，已有但当前禁用的 route contract 绑定仍可保留。
- 标准源保存与 `POST /api/sources/standard/{source_id}/pull` 的 `pull_result` 会额外返回：
  - `warning_count`
  - `warnings[]`
    - `code`
    - `message`
    - `severity`
    - `field`
    - `expected_method`
    - `actual_variant`
- 当 URL 可被回退解析但与字段语义不匹配时，接口仍返回 `ok=true`，但会通过 `warnings[]` 给出强 warning
- `POST /api/sources/standard` 与 `PUT /api/sources/standard/{source_id}` 会在保存后立即探测拉取状态，并返回 `pull_result`：
  - `ok`：是否拉取成功（远程源为任一地址解析出 `>=1` 节点；手动源为 `manual_nodes_text` 解析出 `>=1` 节点）
  - `method`：成功来源（`clash|surge|shadowrocket|manual_nodes`）
  - `node_count`：本次有效节点数
  - `error`：失败时错误摘要（已脱敏，不含 query token）
  - `config_fingerprint`：当前保存配置的稳定指纹
  - `last_success_config_fingerprint`：最近一次成功拉取对应的配置指纹
  - `attempts`：逐地址尝试详情（可能包含 `network_path=direct|proxy`）
    - `request_variant`（可选）：请求/解析变体，如 `ua:clash-verge/2.0`、`format:base64-uri`
    - `parsed_protocol_counts`（可选）：该次尝试按协议解析成功计数
    - `skip_reasons`（可选）：该次尝试被跳过/不支持的原因汇总
  - `last_success_at`：该源最后一次成功时间
  - `ingest_kind=manual_nodes` 时，`POST /api/sources/standard/{source_id}/pull` 表示“重新校验并物化手动节点”，不进行网络拉取
- `GET /api/sources/standard` 返回每个源的状态字段：
  - `config_fingerprint`
  - `last_success_config_fingerprint`
  - `ingest_kind`
  - `manual_nodes_text`
  - `export_config`
    - 仅包含可迁移配置字段：`name/clash_url/shadowrocket_url/surge_url/login_url/quality_group/target_contract_id/source_mode/ingest_kind/manual_nodes_text/enabled/pull_network_mode`
  - `last_pull_attempt_at`
  - `last_success_at`
  - `last_pull_ok`
  - `last_pull_method`
  - `last_pull_node_count`
  - `last_pull_error`：失败摘要文本，给人读；脚本判断失败类型读 `last_pull_reasons`
  - `last_pull_reasons`：最近一次拉取失败时逐个失败尝试列出原因；成功或从未拉取时为 `[]`。每项是 `{method, code, url, message}`，规则见下文「拉取失败原因」
  - `pull_warning_count` / `pull_warnings`：成功导入仍可能有被拒绝的行；按原因展示计数，不回显原始节点 URI 或凭据。
  - `pull_network_mode`
  - `auto_pull_consecutive_failures`
  - `auto_pull_expired`
  - `auto_pull_expired_at`
  - `compatibility`
    - `clash|shadowrocket|surge`
    - 每个目标包含：`supported` / `downgraded` / `pending_validation` / `refused`
  - `qr_assets`
    - `clash|shadowrocket|surge` 三个子字段
    - 每个子字段包含：`source_id` / `field` / `image_exists` / `updated_at` / `detected_url` / `image_url`

自动过期判定规则：

- 仅自动拉取（refresh-policy 定时任务）会累计失败次数。
- 连续失败 `10` 次后标记 `auto_pull_expired=true`（`auto_pull_expired_at` 记录首次过期时间）。
- 手动拉取/保存触发失败不增加该计数。
- 任一成功拉取会清零失败计数并清除过期标记。
- 过期只影响状态展示，不会删除既有缓存节点，订阅下发仍可使用最后一次成功缓存。

标准源二维码资产接口说明：

- `field` 仅允许：`clash` / `shadowrocket` / `surge`
- `POST /api/sources/standard/{source_id}/qr/{field}`
  - `Content-Type: multipart/form-data`
  - 表单字段：
    - `file`：二维码图片（必填，支持 `png/jpg/jpeg/webp`，最大 4MB）
    - `detected_url`：前端已识别出的订阅链接（可选；为空时后端会尝试自行识别）
  - 返回：`{ ok, item, detected_url_source, source_updated, updated_field, pull_result }`
    - `item.detected_url`：最终识别出的订阅链接；若为空表示图片已保存但未识别出可用链接
    - `detected_url_source`：`provided | decoded | none`
    - `source_updated`：是否已把识别结果回填到标准源对应字段（`clash_url / shadowrocket_url / surge_url`）
    - `updated_field`：本次自动回填的字段名；未回填时为空字符串
    - `pull_result`：识别并回填成功后会自动触发一次拉取验证；未识别到链接时为 `null`
- `GET /api/sources/standard/{source_id}/qr/{field}`
  - 返回：`{ ok, item }`
- `DELETE /api/sources/standard/{source_id}/qr/{field}`
  - 删除该字段二维码图片与元数据
  - 返回：`{ ok: true }`
- `GET /api/sources/standard/{source_id}/qr/{field}/image`
  - 返回二维码图片二进制内容（仅管理端使用）

手动拉取接口：

  - `POST /api/sources/standard/{source_id}/pull`
  - 触发单个标准源立即拉取并更新缓存/状态。
  - 返回：`{ ok, item, pull_result }`
  - `pull_result` 字段同标准源保存接口（`ok/method/node_count/error/config_fingerprint/last_success_config_fingerprint/attempts/last_success_at`）。

GoRelay 抓取接口：

- `POST /api/gorelay/accounts/{account_id}/crawl`
  - 成功后会立即执行设备订阅同步（仅同步设备，不触发规则目录或标准源全量刷新）。
  - 响应新增 `device_sync` 摘要字段：
    - `before_count`
    - `after_count`
    - `before_enabled_count`
    - `after_enabled_count`
    - `discovered_count`
    - `added_count`
    - `reenabled_count`
    - `renamed_count`
    - `disabled_count`

标准源协议支持矩阵（拉取解析 + 订阅下发）：

- 通用协议：`http` / `https` / `socks5`
- 代理协议：`ss` / `trojan` / `vmess` / `vless`
- 新增兼容：`anytls` / `hysteria2`（含别名 `hy2`）/ `tuic`
- Clash 拉取：多 UA 探测（`ClashforWindows -> clash-verge -> mihomo`），按“有效节点数最多”选结果
- Shadowrocket 拉取：支持 `[Proxy]` 配置和 Base64 URI 列表（可混合 `anytls://`、`hy2://`、`tuic://`）
- Surge 拉取：支持 `[Proxy]` 新协议行解析（`anytls/hysteria2/tuic`）及扩展 `key=value` 参数抽取
- 下发端（`clash.yaml` / `shadowrocket.conf` / `surge.conf`）均支持 `anytls/hysteria2/tuic` 输出

`last_pull_error` 失败摘要约定：

- 同一 `方式: 错误` 只出现一次，按首次出现顺序保留不同条目；条目内的解析跳过原因保持完整。存量摘要在 API 读出时同样处理，不回写数据库。
- `pull_result.error`、`source_status.standard[id].error`、`aggregate.errors[]` 与 `last_pull_error` 使用同一规则；hub `last_error` 按来源边界拼接，不合并不同来源的相同错误。`/api/status`、`/diagnostics`、core 诊断及刷新响应使用公开投影，读出时不修改历史 runtime 或数据库。
- 摘要及 `attempts[*].url` / `attempts[*].error` / `attempts[*].skip_reasons` 统一处理 URL：去掉 userinfo、query、fragment，支持绝对、协议相对、裸 userinfo、相邻和路径内嵌套的 URL；像令牌的路径段、路径参数及主机标签显示为 `<redacted>`。保留非敏感部分的大小写和路径空段分隔符，清理一次后重复读取保持稳定。新生成的未知协议名先替换本来源的已知密钥，再做启发式清理和 64 个字符的显示截断，超出部分以 `…` 表示；历史 skip_reasons 只脱敏，不追溯截短协议名。
- 已有 URL 路径中的 `,//`、`;//`、`'//`、`"//` 同时按路径段和新的协议相对 URL 检查，取两种解释中需要隐藏的部分；歧义 authority 内含 userinfo 时可能连同主机一起显示为 `<redacted>`。普通 `a//` 路径空段不改写为新 URL。URL 与键值清理先迭代最多三次；仍变化时检查第四次结果，把尚未稳定的非空白片段保守隐藏，并校验不动点；若还存在跨片段依赖则整条隐藏，保证重复读取稳定。
- 清理前先替换同一租户当前标准源 `clash_url` / `surge_url` / `shadowrocket_url` 中提取的已知密钥，再应用 URL 启发式。提取长度至少 4 的 userinfo 用户名、密码和 fragment；敏感 query 键的值、其它符合令牌规则的 query 值、令牌型路径段及主机标签至少 6 个字符，保留词形表中的段除外；带常见扩展名的令牌同时提取去扩展名部分。每个值解码一次，按区分大小写的字面写法匹配：配置中的原文、解码一次后的值和一次编码（大写十六进制）后的写法；query 值另含 `+` 与空格两种写法，主机标签另含小写写法；与相邻标点和嵌套 URL 无关。以 `<redacted>` 开头的已知密钥整体隐藏，较短的已知密钥不拆开已有标记。不在 URL 里、且换了大小写、多层编码或用其它方式编码的副本不按已知密钥匹配，只靠通用启发式。替换只作用于文本字段 `url`、`error`、`last_pull_error`、`errors`、`last_error`、`skip_reasons`、`message`、`cause`、`stack`；其它字段（如 `network_path` 等枚举和标识符）原样返回。历史 runtime、来源摘要及刷新异常投影使用本租户所有标准源的并集，不跨租户共享；配置 URL 字段原样返回，日志不在此范围。改 URL 或删除来源后不保留旧密钥，新读取只依靠当前配置和启发式处理旧诊断，不迁移或回写历史数据。列表和状态读取每个请求按当前配置建一次匹配器，不缓存、不落库、不写日志。
- 来源刷新异常的公开、持久化副本从完整 message / cause / stack 先清理再应用原有长度限制；创建、更新、手动拉取的外层异常也经过相同公开投影。日志行为不在本约定内。
- URL 脱敏是启发式保护：检测时最多进行两次百分号解码，覆盖 hex、UUID、base64/base64url（含填充）、JWT、带常见扩展名的令牌和长度至少 10 的字母数字混合串；JWT 仅指首段以 `eyJ` 开头，或三段均为至少 10 位 base64url 字符的形式，`1.2.3`、`foo.bar.baz`、`a.b.c` 保留。主机只处理长度至少 16 的字母数字混合标签，保留端口、IPv6 和 IDN。普通词形路径（如 `client_subscribe_v2`、`getSubscribeContent`、`internationalization`）保留；像普通词的凭据、较短或其它字符集的令牌、更深层编码可能漏判，`release20261111` 等正常编号及非词形长段也可能误判，不能视为绝对不含凭据。错误文本中带 userinfo 的畸形/超长 scheme 也清理；纯路径文本仍不全面作为 URL 识别。嵌套绝对 URL 后的“标点 + `//`”路径段，若令牌不来自本租户当前已配置的来源 URL，可能不被启发式识别；已知密钥机制不承诺识别这些未知值。
- 裸 authority 逐个检查 `@`，其前的非空白 userinfo 必须非空；满足任一条件即清理：主机后接 `/` 路径、整块以 `/` 开头、或 userinfo 含 `:` 且主机为带点名称（末段至少两个字母）、IPv4、IPv6 字面量或 `localhost`（可带端口，空端口视为未指定）。主机后粘连 `;`、`,`、`)`、`]`、单引号、双引号等边界字符时先分离尾文再判定，IPv6 的闭合方括号保留。按旧隐藏样例优先，`u:p@` 这类空主机、含 `:` 和 `/` 的 userinfo 粘连前缀、带反斜杠尾部的畸形主机也继续清理。`ratio 3:1@peak`、`retry at 12:30@server`、`see docs/README@v2`、`npm pkg @scope/name@1.2.3`、`code:403@upstream` 和纯邮箱保留；`expired:token@host/x`、`status=403/forbidden@gateway/1` 与凭据形态相同，继续隐藏且不恢复隐藏部分的状态信号。`git@github.com:org/repo.git` 因主机后有路径而清理为 `//github.com:org/repo.git`。
- 新旧记录的状态推断均只使用脱敏后的公开文本，URL 自身的主机与路径不参与错误关键词判断；真实 `HTTP 401` / `HTTP 403` / `expired` / `parse` 仍按原规则判断。凭据或 URL 中偶然出现这些词不再导致状态误判，历史数据库原文不回写。
- 网络链路问题：如 `timeout`、`request failed`、`HTTP 4xx/5xx`
- 格式/协议问题：如 `0 valid nodes parsed`、`unsupported protocol anytls`
- 混合问题会同时在 `error` 与 `attempts[*]` 中体现，便于区分“拉不到”和“拉到但解析不了”

拉取失败原因（`last_pull_reasons`）：

- `method`：`clash|surge|shadowrocket|manual_nodes`；刷新本身出错或没有记录尝试时为空串。
- `code`：稳定代码，见下表；表外的值按 `unclassified` 返回。
- `url`：该次尝试的地址，按上文摘要的同一规则脱敏；未配置或与地址无关时为空串。
- `message`：白话说明，不带摘要里的 `(方式, 地址)` 尾注，已脱敏。
- 直连与代理路径失败得一样时只列一次，按首次出现顺序。读出时按本租户当前已知密钥重新清理，不回写数据库。
- 记录原因之前保存的失败读作一项 `unclassified`，`message` 是整条摘要。
- `/api/core/state` 的标准源与 `/api/core/diagnose/source/{source_id}` 带同一字段。

| `code` | 含义 |
| --- | --- |
| `url_not_configured` | 该方式没有配置订阅地址 |
| `http_status` | 上游返回 HTTP 错误状态；`message` 是 `HTTP <状态码>` |
| `timeout` | 请求超时 |
| `request_failed` | 连接、DNS 或 TLS 失败 |
| `invalid_payload` | 响应无法按订阅格式读取 |
| `no_valid_nodes` | 能解析但没有可用节点；`message` 带跳过原因 |
| `fetch_failed` | 拉取时的其它错误 |
| `manual_nodes_missing` | 手动源没有节点文本 |
| `refresh_failed` | 刷新在得到拉取结果前出错 |
| `all_methods_failed` | 拉取失败，但没有记录任何尝试的错误 |
| `unclassified` | 记录原因之前保存的失败，或未归类的代码 |

当标准源设置为 `高质量机场` 时：

- 节点会按名称中的倍率自动分流：`<5x` -> `高质量-低倍率`，`>=5x` -> `高质量-高倍率`
- 未识别倍率的节点不会进入任何质量组（不会写入标准节点缓存）

### Route Contracts

- `GET /api/contracts`
  - 支持 `scenario_id`；默认 `scenario-default`。
  - 默认场景返回：全局用户契约。
  - 非默认场景返回：全局用户契约 + 当前场景私有契约。
  - 每个 item 额外返回：
    - `scope`：`global|scenario`
    - `owner_scenario_id`：全局契约为空字符串，场景契约为 owner scenario id
- `POST /api/contracts`
  - 支持 `scenario_id`。
  - `scenario_id` 为空或 `scenario-default`：创建全局用户契约。
  - `scenario_id=<non-default>`：创建当前场景私有契约。
  - Body：
    - `display_name`（必填）
    - `description`
    - `llm_routing_intent`
    - `routing_action`（`proxy|direct|reject`，默认 `proxy`）
    - `strategy_type`
    - `primary_pools`
    - `fallback_pools`
    - `failure_action`
    - `enabled`
    - `sort_order`
    - `is_default`
  - `id` 由后端生成且不可编辑：
    - 全局契约：`custom-<slug>`
    - 场景契约：`scenario-<scenario_slug>-<slug>`
  - `display_name` 唯一性按当前可见作用域校验：
    - 默认场景：全局唯一
    - 非默认场景：全局契约 + 当前场景私有契约整体唯一
- `PUT /api/contracts/{contract_id}`
  - 支持 `scenario_id`。
  - 所有契约按 owner scope 编辑；预置身份不构成只读限制。
  - `routing_action`：`proxy|direct|reject`，与 ID 独立。proxy 需要有效主池且遵守质量隔离；direct/reject 不携带节点池。
  - `action-direct/action-reject` 是原生动作目标，不能作为契约 ID；代理契约展示名不能占用 `DIRECT/REJECT/REJECT-DROP`、兜底组或 `·自动` 辅助组名。普通质量标签可删除后重新使用。
  - 默认场景编辑全局契约：允许修改完整拓扑与 view 字段。
  - 非默认场景编辑继承的全局契约：只允许修改 view 字段；若提交 `routing_action/strategy_type/primary_pools/fallback_pools/failure_action`，返回 `409 contract topology is managed by its owner scope`。
  - owner scenario 编辑场景私有契约：允许修改完整拓扑与 view 字段。
  - 若契约仍被引用，禁用会返回 `409 contract is still referenced; rebind before disabling`。
- `DELETE /api/contracts/{contract_id}`
  - 支持 `scenario_id`。
  - 所有契约均可删除；预置项删除后不会在重启时补回。
  - 可传 `replacement_contract_id`：事务内迁移所有受影响场景的服务目录、自定义规则、进程规则、外部程序、标准源和默认项，再删除。
  - 替代项必须在每个受影响场景可见且启用；全局契约只能由全局契约替代；标准源要求替代项可接收标准节点。
  - 默认项有其他可用候选时必须显式指定替代，返回 `409 default contract requires an explicit replacement before deleting`；最后一个无引用的契约可删除成为空草稿。
  - 全局契约只能在默认场景删除；非默认场景返回 `409 global contract must be deleted from default scenario`。
  - 场景私有契约只能在 owner scenario 删除；其他场景返回 `409 contract can only be deleted from owner scenario`。
  - 若契约仍被服务目录、自定义规则、进程规则、外部代理程序、标准源等引用，返回 `409 contract is still referenced; rebind before deleting`。
- `GET /api/contracts/{contract_id}/references`
  - 与删除相同的 owner scope；返回 `{ references: [{kind, count, scenario_id}], is_default, can_delete }`。
  - `kind`：`service_catalog|custom_rules|process_rules|external_proxy_programs|standard_sources|default`。
  - `can_delete` 表示无需替代即可删除；最后无引用默认项可退为空草稿。
- `POST /api/contracts/{contract_id}/rebind`
  - 支持 `scenario_id`。
  - Body：`{ "to_contract_id": "..." }`
  - 只允许 rebinding 到当前场景可见且启用的目标契约；四类引用在同一事务中迁移，任一阶段失败全部回滚。
  - 默认场景 rebind 影响全局基线引用；非默认场景只影响当前场景下的引用视图。
  - 返回：`{ ok, counts }`
    - `service_catalog`
    - `custom_rules`
    - `process_rules`
    - `external_proxy_programs`

### Rule Categories

- `GET /api/rules/categories?q=...`
  - 返回分类列表（包含 `assigned_group` / `locked` / `rule_count` / `custom_rule_count`）。
  - 支持 `scenario_id`；各行的分组显示名与 `effective_contract_display_name` 都按本次请求读到的同一份场景契约解析，查询次数不随分类数增长。
- `GET /api/rules/categories/{name}/preview?offset=0&limit=200`
  - 返回规则目录原始规则预览（不包含分类自定义规则，不做 target 重写）。
  - `offset` 默认 `0`，`limit` 默认 `200`，最大 `1000`。
  - 返回：`{ ok, category, total, offset, limit, has_more, items }`。
  - 手动分类固定返回空结果（`total=0`、`items=[]`）。
- `GET /api/rules/categories/{name}/custom`
  - 返回分类自定义规则列表。
  - 支持 `scenario_id`；effective contract / active 按当前场景解析。
  - 规则本身不单独保存 target；响应返回分类当前解析出的去向契约：
    - `category.effective_contract_id`
    - `category.effective_contract_display_name`
    - `category.effective_contract_source`
    - `category.active`
  - `items[]` 也返回相同的 effective contract 视图，不再返回 `effective_group` / `assigned_group`。
- `POST /api/rules/categories/{name}/custom`
  - Body: `{ "rule_type": "...", "value": "..." }`
  - 支持 `scenario_id`；是否允许添加规则按当前场景的 directness + route contract 判断。
  - 分类自定义规则不接受单独 target。
  - 当分类未绑定 route contract 且当前也不是 `DIRECT` 时，返回 `409 category route contract required before adding category rules`。
- `POST /api/rules/categories/{name}/custom/bulk`
  - Body: `{ "items": [{ "rule_type": "...", "value": "..." }], "dedupe"?: true }`
  - 语义与单条创建一致：不接受单独 target；未绑定 route contract 且非 `DIRECT` 时返回同样的 `409`。
- `POST /api/rules/categories/manual`
  - Body: `{ "name": "...", "assigned_group"?: "...", "default_policy"?: "direct"|"proxy"|"group", "default_group"?: "...", "rules"?: [...] }`
  - 若创建结果为 `DIRECT`，允许在同一请求中携带初始 `rules`。
  - 若创建结果不是 `DIRECT`，但请求携带了 `rules`，返回 `409 category route contract required before adding category rules`。
- `PUT /api/rules/categories/{name}`
  - Body: `{ "assigned_group": "<group>" }`
  - 支持 `scenario_id`；非默认场景只修改该场景的分类分配。
  - `assigned_group` 仅允许：`高质量-高倍率` / `高质量-低倍率` / `中等质量` / `低质量大流量` / `""(未分配)`
  - 若分类 `locked=1`：返回 `409 category locked`
- `PUT /api/rules/categories/{name}/lock`
  - Body: `{ "locked": true|false }`
  - 锁定后禁止修改分配（必须先解锁）。
- `POST /api/rules/categories/bulk-assign`
  - Body: `{ "assignments": { "分类名": "目标组名" } }`
  - 支持 `scenario_id`；非默认场景只修改该场景的分类分配。
  - 返回：`{ ok, updated, skipped_locked }`
  - `skipped_locked` 为被锁定而跳过的分类列表。
- `PUT /api/service-catalog/bulk-groups`
  - Body: `{ "assignments": { "分类名": "目录分组名" } }`
  - 支持 `scenario_id`；批量修改 service catalog 的 `catalog_group`。
  - value 允许为空字符串，表示清空目录分组。
  - 这是管理视图分组接口，不修改 `contract_id`，也不要求分类已绑定 contract。
  - 返回：`{ ok, updated, invalid }`
  - `invalid` 为不存在的分类名列表。
- `PUT /api/rules/categories/{name}/pin` / `DELETE /api/rules/categories/{name}/pin`
  - 支持 `scenario_id`；默认场景修改全局 pin，非默认场景只修改该场景的置顶分组。
- `POST /api/rules/pin-groups` / `PUT /api/rules/pin-groups/{name}/rename` / `DELETE /api/rules/pin-groups/{name}` / `PUT /api/rules/pin-groups/reorder`
  - 支持 `scenario_id`；默认场景修改全局 pin group，非默认场景只修改该场景的 pin group。

### Rule Catalog Refresh

- `POST /api/refresh`
  - 手动触发全量刷新（规则目录 + 订阅源 + 设备同步）。
  - Body（可选）：`{ "rule_catalog_mode": "incremental" | "full" }`，默认 `incremental`。
  - 返回 `runtime.source_status.rule_catalog`，用于展示本次规则目录结果与统计：
    - `source`: `github|cache`
    - `mode`: `incremental|full`
    - `downloaded_count` / `reused_count` / `attempted_count` / `succeeded_count` / `failed_count`
    - `tree_not_modified`（命中 tree 304）
    - `cn_cache_source`（`memory|sqlite|network|stale_fallback|none`）
    - 失败时包含 `error`
  - `runtime.source_status.aggregate` 与顶层结果报告当前动作的 `ok`、`partial`、`status`、`attempted_count`、`succeeded_count`、`failed_count` 和 `errors`；有失败时返回 HTTP `502`，同时保留运行时诊断。
  - 规则统计按分类下载尝试计数；TTL 缓存跳过与 SHA 缓存复用不计为本轮成功。Tree `304` 重验计为一次成功检查；目录获取失败计为一次失败。`partial=true` 必须同时存在本轮成功与失败，旧缓存仍可用不代表刷新成功。
  - 标准源批量/单项刷新与 GoRelay 单账号同步只汇总本次实际尝试，不把历史失败、禁用源或缓存当成本轮结果。
- `POST /api/rules/refresh`
  - 仅刷新规则目录。
  - Body（可选）：`{ "mode": "incremental" | "full" }`，默认 `incremental`。
  - `incremental`：按 tree ETag + 分类 source sha 复用本地缓存，仅下载变化分类。
  - `full`：忽略增量复用，重建规则缓存与 CN 判定缓存。
  - 返回：`{ ok, result }`，`result` 字段同上。
  - 目录或分类刷新失败时返回 HTTP `502`，保留 `result` 中的统计与错误。
  - 自动直连判定：
    - 分类名为 `Direct`（不区分大小写），或
    - 该分类的规则行存在显式 `...,DIRECT,...`
    - 分类规则经 `geosite:cn + geoip:cn` 语义判定为中国大陆直连（高置信度）
  - 自动直连分类会被设置为 `assigned_group="DIRECT"` 且 `locked=1`（UI 只读展示）。

### Rule Export / Import

- `GET /api/rules/export`
  - 返回导出 prompt 与 `candidates` 列表（仅允许输出 4 个代理组）。
- `GET /api/rules/pins/export`
  - 返回置顶分组导出 prompt 与 `candidates` 列表。
- `POST /api/rules/import`
  - 支持两种 payload：
    - 直接传 `{ "分类名": "目标组名" }`
    - 或 `{ "assignments": { ... } }`
  - 返回：`{ updated, skipped_locked, invalid_items }`
  - `skipped_locked` 会跳过所有锁定分类。
- `GET /api/settings/llm-export`
  - 返回：`{ ok, item: { rules_preferences, pins_preferences, directness_preferences } }`
  - 三个字段均为服务端持久化的偏好说明文本。
- `PUT /api/settings/llm-export`
  - Body：`{ "rules_preferences"?: string, "pins_preferences"?: string, "directness_preferences"?: string }`
  - 任一字段传空字符串时，导出时会回退到系统默认偏好。

### Policy Backup

- `GET /api/policy-backup/status`
  - 返回：`{ ok, item }`
  - `item` 字段包含：
    - `enabled` / `configured`
    - `repo_url` / `branch` / `subdir`
    - `dirty` / `syncing`
    - `last_result`（`idle|ok|error|reconciled`）
    - `last_sync_at` / `last_commit_sha` / `last_error`
    - `last_sync_run_id`；失败时 `last_error_detail` 包含同步阶段、异常类型、脱敏消息、cause 和受限堆栈
    - `dirty_generation` / `acked_generation`：SQLite durable outbox 的最新 generation 与已确认 generation
    - `outbox_pending_count` / `outbox_oldest_at`：尚未确认的策略变更数量与最早变更时间
    - `reconciliation_required` / `reconciliation_error`：上次外部 Git 写入结果不明确或备份仍不可达时的安全门禁
    - `last_remote_probe_at` / `last_remote_digest` / `last_remote_commit_sha`：启动或 push 后 compare 的非秘密 readback
- `POST /api/policy-backup/sync`
  - 立即触发一次“自有策略资产”导出并提交到 GitHub 私有仓库。
  - 当策略备份未启用或配置不完整时返回 `400`。
- `GET /api/policy-backup/export`
  - 返回当前 DB 真相导出的结构化快照：
    - `manifest`
    - `global.custom_rules`
    - `categories.manual_categories`
    - `scenarios.<scenario>.{metadata,category_overrides,custom_rules,pin_groups,catalog_bindings}`
  - 该导出只包含“自有策略域”，不包含账号、凭据、节点快照和上游规则缓存。
- `POST /api/policy-backup/restore/preview`
  - Body：`{ "ref"?: string }`
  - 从备份仓库读取指定 ref（可留空，默认当前远端分支），返回恢复预览：
    - `source_digest`
    - `snapshot_digest`：本次读取的完整快照内容的 SHA-256，用于绑定后续恢复。
    - `changed`
    - `sections[]`（按 `manual_categories` / `scenario.custom_rules` 等维度给出 `added/removed/changed`）
- `POST /api/policy-backup/restore/apply`
  - Body：`{ "ref"?: string, "expected_digest": string }`
  - `expected_digest` 必须取自最近一次同 ref 预览的 `snapshot_digest`。缺失或重新读取的快照内容发生变化时返回 `409 restore snapshot changed; preview again`，不写入当前策略。旧调用方也必须先预览并传入摘要。
  - 恢复写入在单个数据库事务内完成；任何中途校验或写入失败都会回滚，保留原有策略，且不发布备份变更通知。
  - 用备份仓库中的自有策略资产替换当前 DB 内的 owned-policy 域：
    - 手动分类
    - 全局/场景自定义规则
    - 场景 pin groups
    - 场景 catalog bindings
    - 场景分类 override / lock 状态
  - 不恢复：
    - `rule_category_cache`
    - 标准源 / GoRelay 账号
    - 凭据、节点快照、运行态缓存

### LLM Workflows

- `GET /api/llm/workflows`
  - 返回工作流列表，顺序固定为 `log-routing -> directness -> routing -> grouping`。
- `POST /api/llm/log-routing/sessions`
  - 创建一个日志分流会话，返回 `{ ok, item: { session_id, created_at, updated_at, file_count, evidence_count } }`。
- `POST /api/llm/log-routing/sessions/{session_id}/files`
  - `multipart/form-data` 上传单个日志文件，字段名固定为 `file`。
  - 自动识别并解析 `Surge archive index.json`、`Shadowrocket proxy.db`、`Clash/Mihomo service.log`。
  - 仅抽取 `FINAL / Match / 默认规则` 这类兜底命中证据。
- `GET /api/llm/log-routing/sessions/{session_id}/candidates`
  - 返回 `{ ok, session_id, files, evidence_count, candidate_count, candidates }`。
  - `candidates[]` 包含 `root_domain`、`hosts`、`fallback_hits`、`existing_category`、`existing_route`、`current_match_status`、`sample_evidence` 等字段。
- `POST /api/llm/log-routing/sessions/{session_id}/export`
  - Body：`{ "intent_override"?: string, "sample_evidence_limit"?: int }`
  - 返回 `{ ok, workflow, schema, session_id, snapshot_id, prompt, allowed_actions, available_routes, candidates }`
  - `schema` 固定为 `subhub.llm.log_routing.v1`。
- `POST /api/llm/log-routing/sessions/{session_id}/preview`
  - Body：`{ "snapshot_id": string, "patch": object }`
  - `patch.schema` 必须为 `subhub.patch.v1`。
  - 只允许 action types：`ensure_manual_category`、`set_category_route`、`add_category_rule`、`remove_category_rule`。
  - `set_category_route.contract_id` 必须是当前系统存在且启用的 route contract。
  - 返回底层 patch preview 结果，附带 `workflow=log-routing`、`session_id`、`snapshot_id`。
- `POST /api/llm/log-routing/sessions/{session_id}/apply`
  - Body：`{ "snapshot_id": string, "patch": object, "selected_action_ids"?: string[] }`
  - `selected_action_ids` 缺省时应用全部 action；传空数组时允许返回 `applied_count=0`。
  - 若 `selected_action_ids` 包含未知 id，返回 `400 invalid selected_action_ids`。
  - 若 `snapshot_id` 漂移，返回 `409 snapshot drifted, please export again`。
- `POST /api/llm/workflows/{workflow}/export`
  - Body：`{ "intent_override"?: string, "sample_rule_limit"?: int }`
  - 返回当前工作流的 prompt、快照指纹和结构化输入。
- `POST /api/llm/workflows/{workflow}/preview-import`
  - Body：`{ "snapshot_fingerprint": string, "result": object }`
  - 返回：`{ ok, workflow, changes, invalid_items, skipped_locked, skipped_unchanged }`
  - `changes[].change_id` 是前端用于逐条保留/放弃的稳定标识。
- `POST /api/llm/workflows/{workflow}/apply`
  - Body：`{ "snapshot_fingerprint": string, "result": object, "selected_change_ids"?: string[] }`
  - `selected_change_ids` 缺省时应用全部 preview 变更；传空数组时允许返回 `applied=0`。
  - 若 `selected_change_ids` 包含未知 id，返回 `400 invalid selected_change_ids`。
  - 仍会先校验 `snapshot_fingerprint`，若底层数据漂移则返回 `409 snapshot drifted, please export again`。
  - `directness` 工作流接受后的变更会自动转成手工锁定，后续 routing/grouping 会跳过这些分类。

### Status

- `GET /api/status`
  - 返回运行状态快照 `runtime.source_status`。
  - `runtime.source_status.standard.{source_id}` 在保留 `ok`/`node_count` 的同时，新增：
    - `source_name`: 源名称
    - `pull_method`: 最近成功来源（`clash|surge|shadowrocket`）
    - `pull_node_count`: 最近一次写入缓存的节点数
    - `attempts`: 本轮逐地址尝试详情
    - `last_success_at`: 最近成功时间
    - `unrecognized_multiplier_count`: 高质量机场未识别倍率节点数量
    - `unrecognized_examples`: 未识别节点名称示例（最多 5 条）

### Refresh Policy Settings

- `GET /api/settings/refresh-policy`
  - 返回：`{ ok, item: { rule_catalog_cache_hours, cn_cache_hours, standard_source_auto_pull_enabled, standard_source_auto_pull_interval_minutes } }`
- `PUT /api/settings/refresh-policy`
  - Body：`{ "rule_catalog_cache_hours": int, "cn_cache_hours": int, "standard_source_auto_pull_enabled"?: bool, "standard_source_auto_pull_interval_minutes"?: int }`
  - 约束：`1 <= hours <= 168`
  - 约束：`1 <= standard_source_auto_pull_interval_minutes <= 1440`
  - 修改后立即生效，无需重启

## GoRelay account management

- `GET /api/gorelay/accounts`
- `POST /api/gorelay/accounts`
- `PUT /api/gorelay/accounts/{account_id}`
- `POST /api/gorelay/accounts/{account_id}/crawl`

账号列表使用当前登录用户的工作区；账号 ID 不能跨用户引用。敏感字段不返回明文，列表通过 `has_gorelay_password`、`has_proxy_password_default`、`has_auth_header` 表示凭据是否存在。

#### `selectors_json` 配置（用于账号采集）

`POST /admin/accounts` 与 `PUT /api/gorelay/accounts/{account_id}` 中，`selectors_json` 必须是 JSON object 字符串。

采集决策顺序（API-only + mock）：

1. `selectors_json.mock_rules` 为数组时，直接走 mock 数据采集（测试/联调）。
2. 否则统一按 API-only 采集（登录 + forward 分页 + devicegroup），失败直接报错。
3. `collector_mode` 历史值会自动迁移到 `api_first`，并在 `source_status.compat_warnings` 输出迁移提示。

字段说明（含新增字段）：

- `collector_mode` (string)：有效值为 `api_first`（API-only）。
  - 兼容迁移：空值 / `api_only` / `api_dom_fallback` / `dom_only` 都会自动迁移为 `api_first`。
- `api_base` / `api_base_url` (string)：GoRelay API 基础地址（例如 `https://gorelay.net`）；未配置时会从 `login_url` / `rules_url` 推断。
- `api_login_path` / `login_path` (string)：登录接口路径，默认 `/api/v1/auth/login`。
- `api_forward_path` / `forward_path` (string)：规则接口路径，默认 `/api/v1/user/forward`。
- `api_devicegroup_path` / `devicegroup_path` (string)：入口组接口路径，默认 `/api/v1/user/devicegroup`。
- `page_size` (number)：forward 分页大小，默认 `200`。
- `api_login_payload` (object)：登录 JSON 模板，可使用 `{username}` / `{password}` 占位符。
- `api_login_headers` (object)：登录请求头（可选）。
- `api_headers` (object)：登录成功后抓取 forward/devicegroup 时附加请求头（可选）。
- `api_auth_mode` (string)：API 鉴权头模式，`raw` / `bearer` / `auto`，默认 `raw`。
  - `raw`：`Authorization: <token>`（GoRelay 推荐）。
  - `bearer`：`Authorization: Bearer <token>`。
  - `auto`：先 `raw`，遇到 `401/403` 自动回退 `bearer`。
- `mock_rules` (array<object>)：mock 规则列表；存在时优先级最高。
- DOM 相关 selector 字段（`row_selector` / `rule_name_selector` 等）已废弃，保留仅用于兼容旧配置，运行时会被忽略。

采集结果会写入账号快照 `source_status.collector`，常见值：

- `api`
- `mock`
- `mcp_fallback`（由上游服务在 API 失败后触发）

可选字段：

- `source_status.compat_warnings`：兼容迁移告警（例如历史 `collector_mode` 被自动迁移）。

`mock_rules` 单项示例：

```json
{
  "rule_id": "654856",
  "line_name": "Mac (#654856)",
  "device_name": "Mac",
  "entry_name": "「Lv2」广东隧道「移动入口」",
  "isp": "移动",
  "ip_version": "ipv4",
  "port": 17526,
  "host": "",
  "status": "pending_domain"
}
```

API-only 模式建议：

- 对 GoRelay 显式设置 `api_auth_mode: "raw"`（GoRelay 常见兼容最佳）。
- 若看到 `api collection failed: ...`，优先排查 API 可达性与鉴权配置，再检查 `source_status.compat_warnings` 的迁移提示。

### Devices / Credentials

- `GET /api/gorelay/accounts/{account_id}/devices?include_stale=0|1`
- `PUT /api/gorelay/accounts/{account_id}/proxy-credentials`
- `PUT /api/gorelay/accounts/{account_id}/devices/{device_key}/proxy-credentials`

`GET /api/gorelay/accounts/{account_id}/devices` 返回项新增字段：

- `subscription_count`：当前设备可用 token 数（默认 1/0）
- `entry_count`：当前设备入口数量
- `is_stale`：是否为历史残留设备（默认接口会过滤，需 `include_stale=1` 才显示）
- `links`：GoRelay 导入链接固定指向默认订阅路径（`/sub/device/{subscription_id}/...`），不会跟随非默认 scenario slug 变化
- `preview`：客户端可用性预览（严格模式）
  - `preview.clash.available` / `preview.shadowrocket.available` / `preview.surge.available`
  - `supported_count` / `skipped_count`
  - `reasons`（如 `missing_token` / `subscription_disabled` / `no_supported_nodes`）
  - `reason_text`（用户可见原因文案；字段名不变，内容可随 `Accept-Language` 返回中英文）

### Domain Bindings

- `GET /api/gorelay/accounts/{account_id}/domain-bindings/pending`
- `POST /api/gorelay/accounts/{account_id}/domain-bindings/import`
- `PUT /api/gorelay/accounts/{account_id}/domain-bindings/{binding_id}`
- `GET /api/gorelay/accounts/{account_id}/domain-import-histories?limit=50`
- `DELETE /api/gorelay/accounts/{account_id}/domain-import-histories/{history_id}`

`domain-import-histories` 语义：

- 记录每次“客服回复文本导入”的原文与导入统计（解析条数、变更条数、倍率提示条数）。
- 删除历史时会尝试安全撤销该次导入写入的绑定：
  - 仅当当前绑定 `host_value + updated_at` 仍与该历史记录一致时才撤销。
  - 若绑定已被后续修改则跳过，并计入 `bindings_skipped_drift`。
- 删除后会自动重建快照，返回 `snapshot_id` 与节点统计。

### Snapshots / Subscriptions

- `GET /api/gorelay/accounts/{account_id}/snapshots`
- `POST /api/gorelay/accounts/{account_id}/snapshots/{snapshot_id}/activate`
- `GET /api/gorelay/subscriptions?account_id=...&include_disabled=0|1`
- `POST /api/gorelay/subscriptions/{subscription_id}/disable`

### GoRelay Refresh

- `POST /api/gorelay/refresh` requires the current user's LazyCat identity and refreshes that user's enabled GoRelay accounts.
- `POST /api/refresh` refreshes the current workspace's sources and rules. These endpoints do not use query-token management authentication.

## Internal

- `GET /healthz` is public instance liveness: `ok`, `service`, `instance`, `server_time_utc`, `setup_required`, `access_mode`.
- `GET /readyz`, `GET /diagnostics`, `GET /metrics` require an initialized, authenticated workspace in per-user mode.
- User-specific refresh state is exposed by `GET /api/status` and `GET /diagnostics`.

`GET /diagnostics` 的 `health.egress.proxy_bridge` 字段：

- `setup_required`：`true/false`
- `initialized`：`true/false`
- `process_rss_mb`：当前服务进程 RSS（MiB，保留两位小数；采样失败时为 `null`）
- `runtime_tasks`：resident task 的 SQLite-backed public heartbeat 投影；包含任务状态、最近 heartbeat、连续失败次数、`has_error` 和受限 phase/unit 等 allowlist 字段，不返回原始 `last_error`、异常详情、私有路径或凭据
- `runtime_alerts`：主动告警能力；`transport=https` 表示已配置 HTTPS receiver，未配置时 `ok=false`，不能把日志写入当成已送达告警
- `policy_backup`：策略备份的匿名安全投影，包含 durable dirty generation/outbox 与远端 compare 字段，但不包含 repository URL、分支或错误详情；`healthz=200` 不等于这些任务已 ready。认证管理接口才返回完整配置视图
- `egress.proxy_bridge`：懒猫双路出站诊断
  - `code`：`ok` / `missing_proxy_env` / `invalid_proxy_env` / `proxy_bridge_unreachable` / `proxy_bridge_upstream_failed`
  - `severity`：`info` / `warning` / `error`
  - `summary`：一句话告警摘要，适合管理台 banner；可按 `Accept-Language` 本地化
  - `meaning`：较详细的语义说明，明确“现在到底坏在哪一层”；可按 `Accept-Language` 本地化
  - `repair_hint`：最短修复提示，适合值班时直接照着做；可按 `Accept-Language` 本地化
  - `actions`：按顺序执行的修复动作列表；可按 `Accept-Language` 本地化
  - `required`：当前是否存在 GoRelay 源，因此是否必须具备代理桥接
  - `proxy_url` / `no_proxy`：当前进程实际看到的代理环境
  - `bridge_host` / `bridge_port`：SubHub 解析出的桥接目标
  - `tcp_reachable`：容器到桥接入口的 TCP 可达性
  - `proxy_probe_ok` / `proxy_probe_status_code`：通过代理桥接完成 HTTPS 探测的结果
  - `last_error`：最近一次探测失败的底层错误

`GET /readyz` 约定：

- 就绪返回 `200` + `ok=true`
- 未就绪返回 `503` + `ok=false`（例如未初始化、存储不可写、SQLite integrity 失败、required heartbeat stale/missing、主动 HTTPS 告警未配置、策略备份需要 reconcile）
- `checks.database` 返回实际 SQLite `integrity_check`、foreign-key 错误与表摘要；`checks.runtime_tasks` 返回每个 required task 的 readiness 原因；`checks.runtime_alerts` 返回 HTTPS receiver 配置/能力；`checks.policy_backup` 返回当前策略备份状态
- 已初始化工作区存储不可写时返回 `503` + `ok=false`。未登录返回 `401`；未初始化返回 `409`。此探测不声明上游服务可用。

`GET /diagnostics` 约定：

- 鉴权与工作区加载成功后返回 `200`，包含 `health` 和 `ready`。
- `health.hub` 是当前用户运行时；`health.egress.proxy_bridge` 提供出站诊断。匿名 `/healthz` 不包含这些用户详情。

`GET /metrics` 约定：

- Prometheus text format
- 至少包含 `lzctoclash_http_requests_total`

## 错误约定

- 未授权：`401` / `403`
- 参数错误：`400`
- 资源不存在：`404`

## 订阅链接基址解析

服务生成 Clash/Shadowrocket 链接时，基址优先级为：

1. `APP_BASE_URL`（显式配置时最高优先级）
   - 当 `APP_BASE_URL` 是本机地址（如 `127.0.0.1/localhost`）且端口与当前请求不一致时，会自动回退到当前请求基址，并在页面展示告警。
2. `LAZYCAT_APP_DOMAIN`（自动拼成 `https://{domain}`）
3. `X-Forwarded-Proto` + `X-Forwarded-Host`
4. `request.base_url`

当最终基址为 `127.0.0.1/localhost` 时，前端会提示“仅本机可用，不可外网更新”。

契约初始化只发生一次；新增契约不会隐式成为默认项。标准源创建必须显式指定可用契约。类别显式直连/拦截的有效目标为 `action-direct` / `action-reject`，不依赖目录中某个永久契约。

### 代理客户端维护的 HTTP 补充契约

- 新增 `GET /sub/device/{token}/{scenario_slug}/shadowrocket-{config_id}.conf`，以及默认场景的 `/sub/device/{token}/shadowrocket-{config_id}.conf`。config_id 是订阅身份和场景的稳定哈希（16 位十六进制），任意不匹配文件名返回 404。原 `shadowrocket.conf` 与 `shadowrocket-legacy.conf` 行为保持兼容。
- `links.shadowrocket_url` 发放新文件名，`links.shadowrocket_scheme` 为 `shadowrocket://config/add/<未编码 URL>`。此操作替换默认配置，同名文件覆盖本地修改。前端校验 scheme 中的完整原始 URL。
- Clash 配置的 200/304 响应包含 `profile-title`，以稳定哈希生成的公开场景别名命名，UTF-8 非 ASCII 用 `base64:` 编码；不从 token、设备私密名称生成该标题。
- settings 写入对空 clash_dns_nameserver/clash_dns_default_nameserver/clash_dns_proxy_server_nameserver 返回 400；存量空值渲染恢复默认并在管理诊断告警。开启 TUN 时空 dns-hijack 在渲染层恢复默认并告警。
- 手工类别 rules 与 custom 接口使用同一 rule_type 白名单，非法类型返回 400。
- 管理 preview/summary 继续返回渲染告警，Clash 客户端 YAML 不再含顶层 render-warnings。Shadowrocket forwarding-proxy 仍待实机验证：若被忽略，链式节点可能直连后置家宽；管理诊断与配置注释均提示。
- Shadowrocket ipv6=false 无法关闭 2.2.93 的运行时 IPv6；能力矩阵返回降级说明。
- Clash Mi 导入步骤见 `docs/operations/clash-mi-import.md`。

### Stage-one intent projection warnings

`GET /api/devices/{token}/preview-summary` and `GET /api/devices/{token}/render-preview` retain their response schemas and add management-only `intent-*` warning items to the existing `warnings` and structured `diagnostics.downgraded/pending_validation` buckets. All have severity warning, stable codes and field/category targets; they never independently cause 409. This includes IP-resolution differences, Shadowrocket conditional DNS behavior, IP-only categories with DIRECT fallback and registered unsupported/unverified projections. Code semantics and conditions are in [the subscription contract](subscription-output-contract.md#derived-intent-diagnostics-stage-one) and [the generated inventory](../design-docs/intent-inventory.md). There is no intent write/read API, migration, new approval flow, or front-end change in this phase.

Round two keeps the same HTTP schemas/statuses. New projection warnings include unverified Shadowrocket load-balance/persistent behavior; IP warnings are aggregated per category/target and overlay warnings per named object. Warning messages omit evidence markup; the registry carries evidence. Existing warning text and explicit-setting detection remain baseline-compatible. The signing callback still reads the clock for asset URL exp; route reproducibility tests freeze that clock.

Round three retains the same schemas/statuses and device bytes. Unsupported setting messages name their actual target; evidence-gap warnings name and count concrete declarations. Native failover no longer warns, load-balance warns only for Shadowrocket, and unproven strict selection, rule-type gaps and legacy migration-state overlays use the registered management-only warning codes. See the subscription contract for conditions.

Round four retains the same schemas/statuses and device bytes. Strict contracts produce one warning per client with a count and at most three names; legacy process/external objects that need rebinding now produce their migration-state warnings; codes that could never be emitted were removed from the registry. The `intent-policyir-*` codes stay: the Hub delivery path leaves those PolicyIR fields empty, but internal builder callers can fill them. A blocked `GET /api/devices/{token}/export/clash-bundle.zip` 409 judges host records with the same captured local aliases as the bundle, so `clash-lazycat-host-record-local-target` is reported as before. See the subscription contract for conditions.
