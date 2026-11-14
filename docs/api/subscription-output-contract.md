# Subscription Output Contract

## Subscription ownership

- Management configuration, source caches and rendered artifacts belong to the authenticated LazyCat user's workspace. Public subscription requests resolve that workspace from the device token or public ID; the caller's login identity does not change the owner.
- Tenant registration and device identifiers persist across restarts. Unknown or ambiguous identifiers fail closed. A damaged workspace cannot expose another user's output.
- A new workspace gets a persistent encryption key and signing secret. Existing root storage retains its original signing behavior after the operator explicitly binds `LEGACY_DATA_OWNER_ID`; initialization does not claim another user's historical data.

## Business group and pool boundary

- `BusinessGroup.pool_names` is the explicit routing boundary. A custom group
  must declare the pool names it may use; the renderer never infers pools from
  a display/group name.
- Legacy rule lines that target one of the known quality-group names are
  translated by a fixed compatibility map. Unknown custom targets remain
  unbound until their `pool_names` are supplied.
- An unbound non-default group fails closed to `REJECT`; it is never silently
  expanded to the medium pool or `DIRECT`.
- Route contracts use explicit `primary_pools` / `fallback_pools`; conversion
  to client helper names is an output adapter only.

## Source conversion

- A malformed share-link line is rejected independently; valid lines in the same source can still be imported. Rejection reasons must not include the original URI or credentials.
- Connection identity includes credentials, transport parameters and source/device/quality ownership. Different credentials or pool assignments must survive aggregation; a display-name change alone does not create another connection.
- VMess/VLESS WebSocket and TLS parameters are retained in the canonical node and supported target outputs. Reality is accepted only where its required fields and target representation are known. Unsupported transports or security extensions produce explicit rejection/skip diagnostics instead of silently becoming plain TCP/TLS.
- Native Clash VMess/VLESS/Trojan gRPC nodes retain `network` and `grpc-opts` in Mihomo output. Surge and Shadowrocket reject targets they cannot express; gRPC is not converted to TCP.
- SS SIP002 plugin parameters are parsed as part of the connection. Supported output adapters preserve those options; other adapters report the unsupported plugin.

## Clash

| 项目 | 契约 |
| --- | --- |
| 主订阅 | `clash.yaml` 使用 `proxy-providers`，不内联 `proxies` |
| LazyCat 默认 DNS 主线 | 默认输出 `dns.enhanced-mode=redir-host`、`dns.use-hosts=true`、`dns.respect-rules=true`、`dns.proxy-server-nameserver`；不再默认输出 `fake-ip-filter` / `tun` / `sniffer` |
| provider keys | `high-premium` / `high-standard` / `medium` / `bulk` / `chain-home` |
| 离线包文件 | `clash.yaml` / `providers/*.yaml` / `manifest.json` / `README.txt` / `AUDIT.md` |
| 默认代理组可见性 | 仅保留被业务入口或链式节点实际引用的自动组；未引用的 `·故障转移` / `·手动` 辅助组不作为默认输出契约 |
| provider health-check | 测速仅由自动组的 `url` / `interval` 驱动，不再生成 provider `health-check`，避免重复测速；blocker `clash-provider-health-check-missing` 现在只在自动 use 组和 provider 两层都缺测速时触发 |
| UDP 策略 | 支持 UDP 的节点显式输出布尔值；代理规则后加同条件 UDP REJECT 保护，防止不支持 UDP 的策略跳过规则后直连。明确 DIRECT 规则保持直连；MATCH 前先尝试原策略承接 UDP，再拒绝未承接者 |
| 链式入口语义 | `chain-home` provider 内链式节点通过 `dialer-proxy=链式入口·自动` 走显式链式入口组 |
| blocker code | `clash-build-blocked`，当前 blocker 明细代码为 `clash-referenced-empty-contract` / `clash-cidr-overlap-blocker` / `clash-provider-health-check-missing` / `clash-use-group-empty-fallback-missing` |
| 空组与测速审计 | blocked detail 的 `provider_health.groups_without_empty_fallback` 列出缺少显式空组回退的动态组并阻断；`use_groups_with_duplicate_health_check` 仅在自动 use 组及其 provider 均启用有效测速（URL 与正 interval），且规范化 HTTP(S) URL 不同时列出重复测速组（E-M-019、LINT-MHM-207）。同 URL、无效 URL 或无法静态确定的组合不报告重复；相同 URL 即使 interval 不同也不推断重复。URL 比较去除首尾空白，统一 scheme/主机大小写及默认端口、空路径与 /，忽略 fragment，保留路径大小写与 query。`AUDIT.md` 使用相同判断；重复测速不增加 blocker，保留默认组级测速 |

支持显式 `udp` 的 Clash 协议：

- `ss`
- `socks5`
- `trojan`
- `vmess`
- `vless`
- `anytls`
- `hysteria2`
- `tuic`
- `wireguard`

## Shadowrocket

| 项目 | 契约 |
| --- | --- |
| 主订阅 | `shadowrocket-<opaque-id>.conf` 与兼容的 `shadowrocket.conf` 共用实现，保留内联 `[Proxy] + [Proxy Group] + [Rule]` |
| 主配置节点来源 | 主配置保持自包含 inline 输出；`shadowrocket-nodes.txt` 仅作为叶子节点分享导出，不是 `[Proxy]` 的逐项镜像 |
| 订阅主机兜底直连 | 仅当 `FINAL` 的解析语义为平台原生拒绝目标或 `routing_action=reject` 的契约，且没有可静态确定覆盖该主机的更早规则时，在所有用户及系统规则之后、紧挨 `FINAL` 之前补精确 DIRECT 规则；最终策略为 DIRECT 或代理时不补。已有规则的位置和策略保持不变，LazyCat 的 `DOMAIN-SUFFIX,heiyu.space,DIRECT` 等系统直连覆盖时不重复。域名用 DOMAIN，IPv4/IPv6 字面量用 /32 或 /128 且显式 no-resolve；作用于该主机全部端口和路径，包括非 `/sub/` 请求，不仅是订阅下载。空 URL 不补规则 |
| 订阅主机拒绝诊断 | 更早且可确定匹配的显式拒绝规则不被覆盖；配置注释、管理预览的 `warnings` / `diagnostics.downgraded`、其他 blocker 导致 409 的 `detail.warnings` 共用一次构建的稳定代码 `shadowrocket-subscription-host-rejected`（`severity=warning`、`bucket=downgraded`），自身不触发 409；计算使用实际托管订阅 URL，说明“Shadowrocket 连接时无法更新这份配置”，建议改为可用代理或 DIRECT，或断开 VPN 后更新。按既有输出顺序只识别 DOMAIN、DOMAIN-SUFFIX（本名与子域）、覆盖 IP 字面量的目标 IP-CIDR / IP-CIDR6；不解析 DNS，不推断 DOMAIN-KEYWORD、GEOIP、规则集、逻辑/端口等条件。无法静态判断的规则仍在兜底之前，可在运行时先命中；注释中的拒绝后果以命中该规则为前提 |
| 拒绝语义判定 | 复用 PR 75 的平台原生目标分类，Shadowrocket 原生拒绝目标为 REJECT、REJECT-DROP、REJECT-NO-DROP、REJECT-TINYGIF、REJECT-DICT、REJECT-ARRAY、REJECT-200、REJECT-IMG、REJECT-VIDEO（rules-matrix.md §4 / E-R-149）；契约只按显式 routing_action=reject 判断，默认契约读取 IR 动作。用户契约和策略组名称不表示动作；REJECT-office 等名称的代理契约不会误报拒绝或因 FINAL 名称而补直连例外。原生变体跨端降级同样限于平台已分类目标，不匹配任意 REJECT- 前缀 |
| 远程规则集 | 自有规则保持内联；用户显式 RULE-SET / DOMAIN-SET 引用继续保留。远程 URL 主机须在 VPN 断开时可解析，连接时下载按当前规则走；不可达可能让相关规则跳过，不把保留引用理解为已验证资源可达 |
| update-url | 服务端不输出此字段，包括空值；由客户端保存实际下载地址，避免覆盖更新目标 |
| legacy 配置 | `shadowrocket-legacy.conf` 只返回 `308` 到对应 `shadowrocket.conf`；不再独立渲染，也不再由管理 API 发放 |
| 默认代理组可见性 | 主配置只保留被引用的自动组，不默认暴露未引用的 `·故障转移` / `·手动` 辅助组 |
| 链式入口语义 | 主配置里的链式节点按唯一后置家宽出口生成，保留 `forwarding-proxy=链式入口·自动`；此字段待实机验证，若被忽略，链式节点可能直连后置家宽。配置注释及管理诊断提示该风险 |
| HTTP 管线 section | 当 LazyCat profile 配置了 Shadowrocket HTTP 管线字段时，`shadowrocket.conf` 可额外输出 `[URL Rewrite]` / `[Script]` / `[MITM]` |
| MITM 启用位 | 一旦输出 `[MITM]`，契约要求同时显式输出 `enable = true` 与 `hostname = ...`；不再只写 `hostname` |
| MITM 验证范围 | 2.2.93 已验证 `hostname = host:8443`；不填端口默认 443。禁止全局 `hostname = *`；客户端需生成/安装 CA、开启系统完全信任并启用 HTTPS 解密，保存后重启 VPN，测试允许名单中的主机 |
| Rewrite 激活说明 | Shadowrocket 2.2.93 下载后直接激活 Rewrite，无需再保存一次；此结论不外推旧版 2.2.80 |
| Map Local 语义 | 保留用户存储值但不再输出 `[Map Local]`；已测写法只拦截不交付，输出注释和管理诊断 `shadowrocket-map-local-intercept-only` 提示改用响应 Script |
| Script 语义 | `[Script]` 为正式能力入口；请求脚本与响应脚本都可单独输出，响应脚本默认按 `type=http-response,requires-body=1` 建模 |

Shadowrocket HTTP 管线的补充约束：

- 默认安全边界仍然保守：不会自动生成大范围 `MITM hostname`，也不会把 `Map Local` 当作稳定 mock 数据通道。
- 若同一配置需要响应改写或返回体处理，优先使用 `[Script]`，不要依赖 `Map Local` 的 inline `data=`。
- 新文件名和 `shadowrocket.conf` 共用唯一渲染实现；`shadowrocket-legacy.conf` 继续永久重定向。
- 主配置无法可靠表达的节点传输、TLS 或协议扩展会跳过，并报告 `shadowrocket-inline-unsupported`；节点 URI 分享导出可保留受支持的原始参数。主配置与叶子分享导出的支持范围因此可能不同。

## Surge

| 项目 | 契约 |
| --- | --- |
| 主订阅 | `surge.conf` 输出主配置 + domain-set/rule-set 资产 |
| 默认代理组可见性 | 默认仅输出被业务入口或链式节点实际引用的自动组；未引用的 `·故障转移` / `·手动` 辅助组不视为公开契约 |
| 链式入口语义 | 节点级链式入口通过 `underlying-proxy=链式入口·自动` 体现 |
| 条件组兼容策略 | `smart` 组使用 `#!REQUIREMENT CORE_VERSION>=22 ...`；`url-test` 回退组使用 `... //!REQUIREMENT CORE_VERSION<22`，避免旧版 Core 把整行条件组当注释吞掉 |
| smart 组成员约束 | `smart` 组只允许具体代理节点成员，不允许嵌套策略组，也不再生成 `include-other-group=...` |
| General 原生字段 | LazyCat profile 可额外驱动 `[General] block-quic` / `http-api-tls` / `http-api-web-dashboard` |
| MITM 原生字段 | LazyCat profile 可额外驱动 `[MITM] h2` / `tcp-connection` / `skip-server-cert-verify` |
| blocker code | `surge-build-blocked`，当前 blocker 明细代码为 `surge-referenced-empty-contract` / `surge-cidr-overlap-blocker` |
| reviewer bundle | 作为补充审计工具保留在 `scripts/export_review_bundle.py`，不是主审核入口 |

## Rule-set files

- `PolicyRuleEntry.to_ruleset_line` 只序列化匹配类型、匹配值，以及来源已有的 `no-resolve` / `src` / `extended-matching` 参数；不输出策略或其他尾部字段。策略由主配置中的 RULE-SET 引用决定。此约束同时作用于 Mihomo classical 与 Surge rule-set 资产。
- 不补删来源的 `no-resolve`，也不改主规则序列化；Mihomo 顶层 CIDR 的既有规范化补参行为保持不变（见文末三端表）。

## Warning Codes

当前订阅渲染里会出现的主要 warning code：

- `clash-cidr-overlap-pruned`
- `clash-cidr-overlap-split`
- `clash-cidr-autofixed`
- `clash-domain-ip-autofixed`
- `clash-rule-dropped-invalid`
- `conflicting-rule-target`
- `duplicate-ip-rule`
- `empty-contract`
- `empty-pool`
- `invalid-rule-dropped`
- `mac-only-rule-ignored`
- `surge-cidr-overlap-pruned`
- `surge-cidr-overlap-split`
- `surge-unsupported-node`
- `shadowrocket-inline-unsupported`
- `shadowrocket-subscription-host-rejected`
- `surge-transport-refused`

## Device Delivery Entry

- 设备订阅公开入口不再区分 `lazycat` / `raw` 两种 profile/flavor。
- 管理端复制链接只暴露当前场景的单一路径，订阅内容直接跟该场景 settings/profile 走。
- 显式场景路径 `/sub/device/{token}/{scenario_slug}/...` 是管理端 canonical 入口；默认路径 `/sub/device/{token}/...` 仅作为默认场景别名。

## User-Owned Route Contracts

- 所有契约以当前目录与显式 `routing_action` 为准：proxy 投影到质量池策略，direct 到 DIRECT，reject 到客户端拒绝动作。ID 和展示名称不决定行为。
- 默认去向由场景显式选定；缺少默认、引用不存在/禁用契约时阻止 Clash、Surge、Shadowrocket 配置交付，不静默恢复历史预置契约或改走直连。
- 显式类别直连/拦截使用独立底层动作；删除目录中的直连/广告拦截模板不会删除客户端 DIRECT/REJECT 能力。
- 质量池隔离和空池终止继续生效；契约可编辑不授权跨质量梯队降级。
- 兼容入口 `/sub/clash.yaml?token=...` 与 `/sub/shadowrocket.conf?token=...` 使用同一设备及默认场景的渲染实现。它们保留相同的鉴权、签名与输出限制；不恢复旧的 profile/flavor 分支。

### Trojan 节点导出限制

- 原生 Clash Trojan 的 WS、ALPN 或客户端指纹字段若无法由当前 Shadowrocket 节点 URI 渲染器完整表达，明确拒绝并报告原因；不静默转成普通 TCP。原始 Trojan URI 可保留原查询参数，完整配置的 inline 输出仍按其独立能力边界判断。

## Client compiler maintenance baseline

- Mihomo 最低 1.19.28：`empty-fallback` 需要 1.19.27，`fallback-lazy-query` 需要 1.19.28。版本元数据为说明信息，不按 UA 拒绝订阅。Surge iOS 提示基线为已验证的 5.23.0。
- 英文国家别名大小写不敏感，使用只判断 ASCII 字母的边界：`US01`、`US_01`、`USA-01` 命中美国，`Busan` 不误命中；中文及原有旗帜处理不变。Python 与 Mihomo filter/exclude-filter 共用同样的别名语义。
- Mihomo 成员可能为空的组（use/include-all/filter/exclude-filter/exclude-type）输出 `empty-fallback: REJECT`。provider 不可用且无缓存时对应流量拒绝而非直连。
- proxy-provider 和 rule-provider 默认 `proxy: DIRECT`。订阅及场景隔离的缓存路径不包含 rev 或明文 token；rev 只在 URL 中。最近成功缓存可在源站故障时继续使用；健康源站的新 rev 可能延迟至 interval（1800 秒）更新。
- Mihomo WireGuard `ip` / `ipv6` 均为单个字符串，兼容来源 ip/address/ip6/ipv6 混合列表；同族仅选首个，其余及非法地址告警；显式 UDP 布尔值。
- 三个必需 DNS 列表 nameserver/default-nameserver/proxy-server-nameserver 写入禁止清空；存量空值渲染恢复文档默认值并告警。fallback 存在时显式 `fallback-lazy-query: true`。开启 TUN 时 dns-hijack 不为空，存量空值恢复默认并告警。
- 不向客户端发送顶层 `render-warnings`；管理 preview/summary、诊断及离线 AUDIT 继续承载告警。可选的空 General 字段省略，避免 `key =`。
- Surge VMess 不生成 `encrypt-method=auto`，默认 aes-128-gcm 且 `vmess-aead=true`；alterId>0 的旧节点跳过并解释原因。TUIC v5 使用 `tuic-v5`，v4 使用 `tuic,token=`。
- Surge WireGuard 在 `[Proxy]` 中声明 section-name，独立段使用 self-ip/self-ip-v6/dns-server/mtu 与括号 peer；来源缺 DNS 时跳过，不代选解析器。已移除的 SS 流加密跳过并告警。
- Surge SS/SOCKS5 显式 udp-relay，服从节点覆盖及场景 UDP 默认；全局 proxy-test-url 与 udp-policy-not-supported-behaviour=REJECT；组上不再下发无效 url。
- Surge 主规则和规则集统一把 DST-PORT 映射为 DEST-PORT；NETWORK TCP/UDP 对应 PROTOCOL；GEOSITE、SRC-IP-CIDR 等无已验证等价条件时丢弃并告警。Mihomo 反向把 DEST-PORT 映射为 DST-PORT，PROTOCOL 的 TCP/UDP 映射为 NETWORK（HTTP/STUN 等无等价则告警拒绝）；不支持的 REJECT 变体降级为 REJECT 并说明 HTTP 占位语义损失。
- 解析参数保持 45b792d 的行为，本轮不统一三端的 `no-resolve` 差异，也不递归补写逻辑规则内的 IP 条件。来源自带参数原样保留；系统生成的私网、LazyCat 域名及其他规则保持基线写法。下面表格指用户规则（不含系统规则），Surge 的主规则及规则集资产遵守同一行为：

  | 用户条件（来源未写 no-resolve） | Mihomo | Surge | Shadowrocket |
  | --- | --- | --- | --- |
  | 顶层 IP-CIDR / IP-CIDR6 | 派生意图复现基线：整组选项替换为 no-resolve，含丢弃其他来源参数 | 不补 | 不补 |
  | 顶层 SRC-IP-CIDR | 同样整组选项替换成 no-resolve；派生 UDP AND 条件也保留它 | 无已验证等价条件，沿用既有过滤/告警 | 沿用既有字段及告警边界 |
  | 顶层 IP-ASN / GEOIP | 不补 | 不补 | 不补 |
  | AND / OR / NOT 内部的 IP 条件 | 不补 | 不补 | 不补 |
  | 来源已写 no-resolve | 保留 | 保留 | 保留 |

  IP-CIDR、IP-CIDR6、IP-ASN 和 GEOIP 均可能依赖域名解析后分流，无条件补写会改变路由；保留基线差异不代表其行为一致。Shadowrocket 的域名命中还受兜底策略影响，目前只在非 REJECT 兜底且系统代理路径验证，skip-proxy/TUN 有差异。
- 存量不可表示规则与新规则共用目标 lowering：例如 UID 要求已确认的 Linux/Android 目标，当前 DeviceSubscription 没有可信目标 OS，不能从设备名、UA 或服务端平台推断支持。故三端均不输出 UID（包括逻辑条件内的 UID），库记录保留；管理预览 warnings、refused 诊断及离线 AUDIT 给出目标限制和改用受支持条件／删除旧规则的迁移提示。导出仍成功，但用户必须审核被拒规则后的路由变化。
- 原生拒绝策略按平台共用分类：Surge 和 Shadowrocket 保留 REJECT-DROP / REJECT-NO-DROP / REJECT-TINYGIF；Mihomo 仅保留 REJECT-DROP，其余两种降级为 REJECT 并告警；Shadowrocket 专有的占位变体迁往 Surge/Mihomo 时同样告警降级。原生策略不计入缺失的路由契约。
- Shadowrocket inline 使用 password=UUID、VMess alterId=0/method=auto、peer、tls=true、obfs=websocket/obfs-uri/obfs-host；支持 VLESS Reality publicKey/shortId 和已验证 vision flow、Trojan WS、WireGuard 单行、TUIC version=5。SS obfs 插件仍要求 URI 导入。UDP 显式 1/0，服从来源和场景设置。
- Shadowrocket 未验证的 client_fingerprint、ALPN、udp_relay_mode 等默认不生成并告警；显式跳过校验使用 allowInsecure=1 并强告警，不默认跳过。未验证 flow/packet encoding 拒绝 inline，保留 URI 路径。
- Shadowrocket 节点名按大小写不敏感去重，组成员同步引用新名。`=`、`#`、`//`、行首 `[` 保持原行为，待实机验证。
- Shadowrocket `ipv6=false` 在 2.2.93 无法关闭运行时 IPv6；字段仅保留偏好，能力矩阵和诊断提示限制，限制流量需显式规则。
- 新 Shadowrocket URL 使用按订阅+场景身份哈希的安全 ASCII 文件名，不包含私密设备名。`shadowrocket://config/add/<未编码 URL>` 会下载并替换默认配置，同名文件覆盖本地手改；旧 URL 持续可用。
- Clash Mi 导入和更新说明见 `docs/operations/clash-mi-import.md`；应用覆写可改变内核运行结果。
- 来源拉取使用已验证格式的 Surge/Shadowrocket UA；Clash UA 保持不变。不伪造 X-Surge-Unlocked-Features 授权。

## Derived intent diagnostics (stage one)

All subscription renderers derive a frozen configuration intent and project it to the existing client compiler. Settings persistence, client bytes, source no-resolve semantics, PR 75/77 behavior, and existing blockers are preserved. The executable inventory and all projection-specific warning codes are generated into [the intent inventory](../design-docs/intent-inventory.md); architecture and active-value conditions are in [the design](../design-docs/configuration-intent.md).

- `intent-ip-dns-client-default-differs`: an unqualified top-level CIDR uses Mihomo no-resolve but Surge/Shadowrocket preserve their previous implicit resolution behavior. It explains that Mihomo does not actively resolve at this rule (an already resolved address may still match), Surge may resolve first, and Shadowrocket 2.2.93 behavior depends on FINAL and system-proxy vs TUN path (E-R-152/E-R-167/E-R-186/E-R-191).
- `intent-shadowrocket-ip-dns-conditional`: IP rules exist on Shadowrocket; FINAL,REJECT does not resolve domain requests in measured cases, while proxy/DIRECT without no-resolve can resolve on the measured Safari HTTP system-proxy path. GEOIP with skip-proxy does not match; other paths remain unverified.
- `intent-ip-only-category-direct-fallback`: a non-system category contains only IP-CIDR/IP-CIDR6/GEOIP/IP-ASN and the explicit default action is direct. When no usable address is available and no later rule matches, domain traffic falls through to DIRECT. The warning is conditional, because Surge and measured Shadowrocket non-REJECT paths may resolve and match. Mixed categories, system-only rules, and non-direct defaults do not trigger it.
- `intent-<family>-<target>-unsupported` / `intent-<family>-<target>-pending-validation`, plus the registered overlay codes: the specific field in `target` cannot be projected equivalently or lacks runtime proof. Messages describe traffic consequences and a corrective action. The complete stable code list is the generated inventory, not this pattern alone.

All new items have severity warning and appear only in authenticated management `warnings` and `diagnostics.downgraded` or `diagnostics.pending_validation`. They do not add blockers/409s, device comments, or downloadable AUDIT.md entries. Existing diagnostics and their device comments remain intact. Backend message text is currently shown directly; no new front-end translation mapping is introduced.

Round three corrects the target name only on unsupported setting projections; pending-validation messages do not claim the native field is absent. `intent-routing-evidence-gap-<target>` now counts concrete declarations and names at most three rules/contracts; it is absent when no concrete object can be identified. `intent-contract-strict-<target>-pending-validation` identifies the contract whose cross-client selection equivalence remains unproven. Failover has direct native documentation/experiment support and no longer adds a warning; load-balance warns only for Shadowrocket's unverified `persistent=1` behavior. Native group records are platform-scoped, not cross-client equivalence claims. DSCP, SUB-RULE, PROCESS-NAME-REGEX and PROCESS-PATH-REGEX have explicit per-target gap diagnostics; accepted text does not establish runtime support. The two `intent-<process|external>-migration-state-surge-pending-validation` codes describe named legacy overlays needing contract rebinding, alongside the unchanged `needs-rebind` warning. The full source/evidence and exact codes remain in the generated inventory.

Round four keeps client bytes and existing warnings unchanged. `intent-contract-strict-<target>-pending-validation` is now one warning per client: it counts the enabled strict proxy contracts, names at most three, and states that client's gap (each client renders strict as a fallback group; switching to the backup pools, REJECT or DIRECT once the primary pool is unavailable has no direct evidence). The migration-state codes follow `migration_warning` alone, because Hub disables every object that needs rebinding; the message states that the overlay is unavailable until rebinding. The registry no longer lists codes that cannot be emitted: cross-client native group and DNS/TUN records are `not_projected` outside their own client, and `intent-legacy-shared-value-diverged` is removed while no setting is classified as shared. Map Local, IPv6 and Surge-only runtime messages describe the target client's own behavior.

The PolicyIR dns/tun/sniffer/rule-provider/HTTP-processing fields are empty on the Hub delivery path; those sections come from Profile settings during projection, and their settings rows carry the diagnostics. Internal builder callers may still fill the fields (Surge renders a caller's `dns` as `dns-server`), so the `intent-policyir-*` codes stay registered for the owning and unsupported clients and are reported when a field is non-empty. Surge counts only the strict contracts it renders as fallback groups: a contract without renderable primary pools is written as `select, REJECT` and is not counted, and the warning is omitted when none remains. `intent-policyruleentry-rule-type-clash-pending-validation` is one warning per client that counts and names (at most three) the rule types Mihomo drops (UID, PASS, PASS-RULE, REMATCH-NAME); the code name is unchanged.

Pure rendering takes local-host aliases and offline generated_at as explicit delivery inputs. HTTP boundaries capture them using the prior behavior and timestamp format; an internal offline builder invocation that omits generated_at uses a deterministic empty stamp. Freeze all delivery inputs when comparing bytes.

### Round-two intent corrections

- DNS policy is derived once after rule compilation and bound to stable rule identity, never an uncompiled index. Normalizers read explicit projected options only. All three historical Mihomo CIDR types (including SRC-IP-CIDR) retain replacement with no-resolve and removal of other options. Changing a frozen policy changes both main and rule-provider bytes; legacy inputs remain identical.
- Snapshotting retains baseline Infinity/NaN acceptance in node raw data. Source rejection is a separate, unimplemented behavior candidate.
- IP resolution warnings aggregate by category and target, with counts and at most three examples. Overlay warnings aggregate by process/program, using human names. Blocked/standalone or intentionally different defaults do not trigger shared drift. Evidence is registry data, never user message text.
- Shared/adapted classifications require direct field/value evidence on every target. DNS/TUN are native namespaces, control APIs are separate standalone interfaces, and metadata has a non-projecting class. strategy_type=load-balance on Shadowrocket keeps persistent=1 but warns about unverified stickiness/session routing. UDP defaults really bind node udp/udp-relay on all three targets; diagnostics explain the measured protocol scope and different failure behavior.
- Signed asset URLs still read the clock during rendering to compute exp; this baseline behavior is preserved. Route determinism requires a frozen signing clock; changing it changes only exp/signature. Moving that clock input to the boundary is a future behavior/implementation candidate.
