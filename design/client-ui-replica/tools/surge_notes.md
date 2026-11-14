
## more-advanced-http-api  (首页›通用›更多设置›高级›HTTP API & Web 面板) sheet ✕ / ✓
- G1: HTTP API toggle ON | footer: 让另一个 App 或者设备通过 HTTP API 控制 Surge 功能。
- G2: 端口 6171 (value) ; 密码 <redacted> (value)
- G3: 允许由 Wi-Fi 控制 toggle ON | footer: 默认仅允许本地程序访问 HTTP API，开启后将允许 Wi-Fi 网络访问。
- G4: HTTPS toggle OFF | footer: 使用 HTTPS 替代 HTTP 协议。需要先配置 MITM 的 CA 证书，同时需要在客户端设备上手动安装并信任 CA 证书。
- G5: Web 面板 toggle OFF | footer: 开启该选项后可以通过浏览器控制 Surge。
- G6: API 在线手册… (link, blue) — not entered (external link)
- screenshot redacted (密码)

## more-advanced-advset-warning: on entering 高级设置 an alert 「警告」: 调整这里的任何一项设置均有可能引发各种问题。请先阅读各项设置的说明，明确理解该设置的意义后再进行调整。 button 好的 (single acknowledge; tapped)
## more-advanced-advset (高级›高级设置) push page, back <, no save button seen (edits likely live?)  shots _1.._7
- 路由: 包含所有网络请求 off / 包含本地网络请求 off / 包含 APNS off / 包含蜂窝服务 off / 包含设备通信 off
  footer: 默认情况下，部分请求可能不会被 Surge 接管。比如应用可以强行绑定物理网卡以绕过 Surge VIF。开启该选项后可以保证所有请求都由 Surge 所接管，没有泄漏，此时可将 Surge 当做防火墙使用。如果还想让 Surge 处理所有本地网络的请求，可开启包含本地网络请求选项。开启这些选项会引起严重的副作用，如 AirDrop、Xcode Debugger、Surge Dashboard USB 模式等无法正常使用，请仅在需要的特定情况下开启。
- show-error-page: 开启 ON | 当请求遇到错误时显示 HTTP 错误页面。
- show-error-page-for-reject: 开启 OFF | 如果请求是普通 HTTP 请求，为 REJECT 策略显示错误网页。
- auto-suspend: 开启 ON | 当发现当前网络由 Surge Gateway 所接管时，自动暂停 Surge iOS。
- encrypted-dns-follow-outbound-mode: 开启 OFF | 默认情况下，加密 DNS 查询使用直连出站。启用此选项会让 DOH 跟随出站模式设置和规则。
- encrypted-dns-skip-cert-verification: 开启 OFF | 跳过加密 DNS 服务器证书验证，这是不安全的。
- allow-dns-svcb: 开启 OFF(partially seen) | iOS/macOS 系统可能会执行 SVCB 记录 DNS 查询而不是标准的 A 记录查询。这会导致 Surge 无法返回虚拟 IP 地址。因此默认情况下，禁止 SVCB 记录查询以强制系统执行 A 记录查询。
- hijack-dns: text placeholder 逗号分隔 (empty) | 默认情况下，Surge 仅对发送到 Surge DNS 地址（198.18.0.x）的 DNS 查询返回伪造的 IP 地址。发送到标准 DNS 的查询将被转发。某些设备或软件总是使用硬编码的 DNS 服务器。（例如，Google 音箱始终使用 8.8.8.8）。您可以使用此选项劫持查询以获取伪造地址。您可以使用 hijack-dns = *:53 劫持所有 DNS 查询。
- always-real-ip: text 逗号分隔 (empty) | 此选项要求 Surge VIF 处理 DNS 查询时返回真实 IP 地址，而不是伪造的 IP 地址。DNS 请求包将被转发到上游 DNS 服务器。
- force-http-engine-hosts: text 逗号分隔 (empty) | 强制让 Surge 将 TCP 连接视为 HTTP 请求…（含通配与示例列表）
- always-raw-tcp-hosts: text 逗号分隔 (empty) | Surge 会自动对发往 80 与 443 端口的 TCP 请求进行协议嗅探…可以将主机名添加到此处，Surge 将不会对这些请求进行协议嗅探。
- always-raw-tcp-keywords: text 逗号分隔 (empty) | 在进行协议嗅探时，如果 HTTP Header 中出现特定关键词，则将该请求回退到原始 TCP 处理…
- tun-excluded-routes: text 逗号分隔 (empty) | Surge VIF 只能处理 TCP 和 UDP 协议。使用此选项绕过特定的 IP 范围以允许所有流量通过。注意：此选项仅适用于 Surge VIF…结合 'skip-proxy' 和 'tun-excluded-routes' 确保特定的 HTTP 流量绕过 Surge。
- tun-included-routes: text 逗号分隔 (empty) | 默认情况下，Surge VIF 接口将自己声明为默认路由。但是，由于 Wi-Fi 接口有更小的路由，一些流量可能不会通过 Surge VIF 接口。使用此选项添加更小的路由。
- skip-proxy: text placeholder 空 (empty) | 注意：此选项的目的并不是阻止请求通过代理发出。在 iOS 版本中，此选项会强制将连接这些域名/IP 段的流量交由 Surge VIF 处理…（含写法列表）
- exclude-simple-hostnames: 开启 ON | 就像 skip-proxy 参数一样。此选项让使用简单主机名（不带点）的请求由 Surge VIF 而不是 Surge 代理处理。
- proxy-test-udp: text 空 | 代理的默认 UDP 测试参数。例如：apple.com@1.0.0.1
- wifi-access-http-auth: text 空 | Require authentication for Surge HTTP proxy service. E.g.: username:password
- proxy-restricted-to-lan: 开启 ON | Restrict proxy or gateway services to only accept devices from the current subnet. Enabled by default.
- icmp-forwarding: 开启 ON | 允许 Surge 转发 ICMP ping 数据包，关闭后 ping 将无法使用。
NOTE: current profile sg3-b shows always-real-ip / tun-excluded-routes / skip-proxy empty although SubHub writes them -> sg3-b may not be a SubHub profile or values shown differently. unverified.

## more-advanced-netopt (高级›网络优化) push, shots netopt, netopt_2
- 并发 DNS 查询: value 开启 (disclosure/picker) | Surge 会向所有 DNS 服务器并发进行请求，并使用最快的响应结果。
- Optimistic DNS: 开启 | Surge 将沿用已过期的 DNS 结果缓存，同时进行新的 DNS 查询。当域名配置了过短的 TTL 时可有效减少不必要的等待时间。
- TCP CDN 优化: 开启 | 如果域名包含多个 A/AAAA 记录，Surge 将并发向所有地址发起连接，最后选择速度最快的连接。
- 增强版 Wi-Fi 助理: toggle OFF | Surge 会在 Wi-Fi 网络不佳时尝试使用数据网络建立连接。该功能将对所有 TCP 连接生效，请仅当使用不限量的数据流量套餐时开启。
- 混合网络: toggle OFF | 无论 Wi-Fi 信号如何，总是尝试并发使用 Wi-Fi 和数据网络建立连接。该选项可显著改善在弱 Wi-Fi 和网络切换时的网络体验。该选项对所有 TCP 连接和 DNS 查询生效。请仅当使用不限量的数据流量套餐时开启。
- 游戏优化: toggle ON | 开启后将在系统负载非常高，数据包处理出现延迟时，优先处理 UDP 数据包。
## more-advanced-latency (高级›延迟测试) sheet ✕/✓
- 互联网测试 URL: text http://probe.lab.test/generate_204 | 使用网络诊断功能时访问的 URL。
- 代理测试 URL: text http://probe.lab.test/generate_204 | 测试代理策略时的 URL。
- 测试超时（秒）: 3 | Surge 将向该 URL 发送一个 HTTP HEAD 请求。测试只关心是否收到了返回数据，并不关心数据内容。仅支持 http:// 协议。
## more-advanced-subnet (高级›子网设置覆盖) push
- ⊕ 新增子网设置… (blue action) | 你可以在特定网络下覆盖部分设置或临时禁用 Surge。  (not entered: add form)
- list: 无项目 | 在任意一行上长按可调整顺序。
## more-advanced-geoip (高级›GeoIP 数据库) push
- header GeoIP 数据库: 最后更新 11/11/26 01:55 (value) ; 现在更新… (blue action, NOT tapped) | Surge 使用由 MaxMind 创建的 GeoLite2 数据库。
- header 自定义 GeoIP 数据库 URL: text placeholder 自定义 GeoIP 数据库 URL (MaxMind 格式) ; 自动更新 toggle ON | 启动该选项后 Surge 将每周自动进行 GeoIP 数据库更新。
- note: last-update time 01:55 is during this session; I did not tap 现在更新 — likely the app's own auto update.
## more-advanced-ipv6 (高级›IPv6) push
- IPv6 DNS 查询 toggle OFF | 启用完整的 IPv6 支持。具体来说，启用此选项后，在访问域名时将查询该域名的AAAA记录。即使未启用此选项，也可以通过直接访问IPv6地址来访问IPv6网站。开启该选项可能会略微增加延迟，如果DNS服务器在查找AAAA记录时出现问题，则可能显著增加延迟。仅在必要时启用。
- IPv6 VIF popup 禁用 ⌃⌄ | 允许 Surge VIF 处理 IPv6 请求…  自动：仅在当前网络支持 IPv6，且 IPv6 查询开关打开的状态下开启 / 总是：总是开启 IPv6 VIF。/ 禁用：完全关闭 IPv6 VIF。
## more-advanced-takeover (高级›接管模式) push, single-choice list with subtitles
- 默认 ✓ 标准接管模式，以 TUN 设备对全局网络进行接管。
- 代理接管优先: 在标准接管模式的基础上，同时配置系统代理，以此减少接管请求时产生的额外开销。但是部分应用可能会拒绝在代理模式下工作。
- 非默认路由: 与标准模式类似，但是不配置 TUN 设备为默认路由，使用若干个子路由条目进行接管。以此绕过在标准模式下，HomeKit Camera 无法连接的问题。
## 日志等级 popup notify — not opened (picker, avoid changing)

## home-dns (首页›通用›DNS 卡片›DNS 设置) sheet ✕/✓  shots home-dns_1,_2
- header DNS 服务器: single-choice 使用系统 DNS 服务器 / 使用自定义 DNS 服务器 ✓ / 混合系统和自定义 DNS 服务器 | 你可以使用该选项强制替代系统的 DNS 服务器设置，使用 , 分隔多个服务器。为了性能考虑 Surge 会向所有服务器并发进行请求。
- header 自定义 DNS 服务器: list rows with ⊖ (value <lan-host> lab LAN) ; ⊕ 增加服务器…
- header 加密 DNS: text placeholder 加密 DNS (empty) | 如果在此配置了 DNS 服务器，传统 DNS 将仅用于连通性测试和解析服务器 URL 中的域名。支持的协议：DNS over HTTPS: https://example.com / DNS over HTTP/3: h3://example.com / DNS over QUIC: quic://example.com / DNS over TLS: tls://example.com / DNS over TCP: tcp://example.com  DNS over TCP 未加密，默认使用 53 端口，请仅用于可信服务器。
- group: Surge Private DDNS (disclosure) ; 代理请求本地 DNS 映射 toggle OFF | 默认情况下，使用代理策略时域名解析一定在远端服务器上进行。开启该选项后，如果访问的域名配置有本地 DNS 映射，Surge 将使用本地 IP 地址进行请求，不在远端进行解析。仅对配置了 IP 地址的本地 DNS 映射生效。
## home-dns-ddns (DNS›Surge Private DDNS) push title "Surge DDNS"
- 解析 Surge DDNS 域名 toggle OFF | (approx) Surge Mac 可将其外部 IP 地址与 .sgddns 域名绑定，你可以在其他使用 Surge iOS 或 Surge Mac 的设备上访问该域名。数据由 iCloud 进行同步，不可在公网访问该域名。
## home-local-dns (DNS 卡片›本地 DNS 映射) sheet ✕/✓ ; bottom search field 搜索
- ⊕ 新增… | 该功能基本等同于 /etc/hosts。 ; list 无项目
## home-proxies (通用›代理服务器) sheet ✕/✓
- header 代理: rows name + blue badge "Shadowsocks" + server (ss-a/ss-b/ss-c lab LAN) + chevron ; ⊕ 添加代理…
- header 策略组: ⊕ 新的策略组… | 在任意一行上长按可调整顺序。  (no groups in sg3-b)
- header 选项: UDP 回退行为 popup 阻止 ⌃⌄ | 并非所有代理服务器都支持 UDP 转发，当一个 UDP 会话尝试使用一个不支持 UDP 转发的代理服务器时，Surge 默认会回退至直连。可修改为阻止以避免潜在的隐私泄漏隐患。
## home-proxy-edit (代理服务器›ss-a) sheet title 代理 ✕/✓ ; only one node recorded; shots _1 (redacted) _2 _3
- header 名称: 名称 = ss-a (text)
- 代理类型: Shadowsocks (disclosure)
- header 服务器信息: 服务器地址 <redacted> ; 端口号 <redacted> ; 加密方式 <redacted>(disclosure) ; 密码 <redacted>(masked) ; UDP Relay toggle ON
- header 选项: Obfs Disabled (disclosure) ; Obfs Host placeholder 默认
- TCP Fast Open (Experimental) toggle OFF ; IPv4 & IPv6 双栈 (disclosure) | 该选项仅影响和代理服务器间的连接，因此仅当服务器主机名为域名时有意义。若配置了跳板代理，由于在跳板远端进行 DNS 解析，该选项无效。
- 屏蔽 QUIC 流量 popup 自动 | 通过代理进行 QUIC 流量转发可能产生性能问题，开启该选项将阻止 QUIC 流量，以使得客户端回退至传统 HTTPS/TCP 协议。
- Shadow TLS Version Disabled (disclosure) | Shadow TLS 是一个流量混淆插件，可以将代理流量伪装为真实的 TLS 流量。详细信息请查看该项目的 GitHub 页面说明。
- 覆盖全局测试 URL text placeholder http(s)://
- 通过另一个代理连接 (disclosure) | 使用一个代理连接另一个代理，该功能又被称为代理链或跳板代理。
## home-rules (通用›代理规则) sheet title 规则 ✕ / ••• / ✓ ; bottom search
- ⊕ 新增…
- list: rj.c.lab.test [DOMAIN] ss-a ; lab.test [DOMAIN-SUFFIX] ss-a ; 默认策略 [FINAL green] REJECT (chevrons)
- header 选项: 在 DNS 失败时使用默认策略 toggle OFF | 如果 DNS 查找失败，请使用 FINAL 规则，否则请求将失败。
- ••• menu not opened (may contain import/export)
## home-ponte (通用›Surge Ponte 卡片›配置) sheet with ONLY ✓ (no ✕); loads with spinner ~3s
- header 已注册设备: 没有已注册的设备 | Surge Ponte 是你在运行 Surge Mac 与 iOS 设备间的私有网状网络。• 零配置需求。• Surge 会自动选择最适合的通道建立连接。• 始终端到端加密，并且加密密钥通过你的 iCloud 同步。• 除非你选择代理服务器，否则你的数据不会经过第三方服务器。
- 使用代理 (disclosure) | 如果已在远端设备上配置使用代理进行 NAT 穿透，最好选择与之相同的代理，但这并非必须。请阅读手册以了解更多信息。
- 接受分享邀请… (blue action, not tapped) | 默认情况下你只可以访问自己 iCloud 下的 Ponte 设备。通过分享功能，可以访问其他 iCloud 下注册的 Ponte 设备，请在先对应的 Surge Mac 上获取确认码。
- 在线手册… (link, not tapped)
- 调试信息 toggle OFF | 开启该选项后，每次在 Ponte 进行连接时，Surge 会使用推送消息显示 Ponte 的连接状态。
- EXIT NOTE: swipe-down & wheel did not dismiss; closed with the only ✓ (完成) button, no field changed.
