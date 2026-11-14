# 覆盖记录

图例：inventory 每一行带 `layer`（profile 写进配置 / app 只在本机 / action 动作）和 `subhub`（写入 / 只写一部分 / 不写 / 只在手机本机 / 还没核对 / 不适用）。

## Shadowrocket 2.2.93 (3488) — 已完成

遍历了：首页（全局路由、分组、场景、一条节点详情）、配置 tab（模块、配置编辑器全部 10 个分区 + 规则集 URL / 脚本 URL，以及每个分区的新建表单与类型/策略选择页）、设置 tab 全部可进的子页、数据 tab（日志三页、服务器节点两项）。

没遍历及原因：

| 入口 | 原因 |
| --- | --- |
| 配置编辑器 › 编辑纯文本 | 显示整份配置原文，含订阅与节点敏感值 |
| 编译配置 / 扩展 / 导出配置 / 复制 / 替换策略 / 测试规则；配置 tab 的 恢复默认配置 / 导入… / Wi-Fi 上传 / 测试规则 | 动作页，只记入口 |
| HTTPS 解密 › 证书 | 生成 / 安装 CA 的动作页 |
| 设置 › 位置 / 通知 / 剪贴板 | 可能跳 iOS 设置 |
| 设置 › 语言、TCP 子页（TLS / 指纹 / 最大读取长度）、小组件 › 服务器节点、分组 › 简单模式 | 选择页；点选会改值；选项已在 app-guide 记录的不重复进 |
| 捷径各行、外观 › 重设颜色 / 复制网址、节点 › 分享 / 复制 JSON / 复制网址 | 动作，部分会写剪贴板 |
| 诊断 › VPN 日志 / 网络 / 路由表 / 系统代理设置、数据 › 统计、日志文件 | 只读诊断数据，含本机网络与访问记录 |
| 首页节点行本体、模块行本体、配置行长按菜单 | 点按即切换节点 / 启停模块 / 切换配置 |
| 正文重写、本地映射的列表页 | 空列表，只截了新建表单 |
| 规则类型选择页下半（AND / NOT / OR） | 未滚动；app-guide 已记录 |

### 与 app-guide 对不上的地方（供回写 skill）

- 配置 tab 顶部入口现在是「恢复默认配置 / 导入… / Wi-Fi 上传 / 模块 / 测试规则」，左上扫码、右上 +；app-guide 写的是「顶部模块入口；+ → 从 URL 下载」。配置行右侧有 ⓘ，点 ⓘ 直接进配置编辑器（app-guide 只写了长按 → 编辑配置）。
- 列表里看不到 app-guide 说的「绿点 + ✓ = 默认配置」标记（本机主题下没有显示）。
- 设置 tab 新增：高级 › 小组件、捷径、外观；隧道 › Tailscale（整页新入口：启用、低电量模式、认证密钥、控制服务器 URL、出口节点、始终使用 DERP、使用 Tailscale 子网、重置 Tailscale 标识）；其它 › 自动旋转。规则策略列表多出 TAILSCALE。
- 设置 › 诊断 新增「滚动频率」（1 / 2 / 3 / 4 / 12 / 24 小时，当前 1）。
- 设置 › 隧道 › 隧道 的行名已中文化：强制路由 / 包括所有网络 / 包括本地网络 / 包括 APNs / 包括蜂窝服务（app-guide 写 enforceRoutes、includeAllNetworks 等英文名）。
- 设置 › 按需求连接 多了「按需求规则」分区（默认一条：行为 连接，网络 任意；规则表单有 SSIDs / 域名 / DNS / URL 探针）。
- 设置 › 代理 › 代理共享 的「IP」行显示手机局域网 IP；「HTTPS 解密」当前为开（与 app-guide 一致）。
- 数据 › 日志 › 代理 的「启用日志记录」当前为 **开**；设置 › 诊断 的「启用日志记录」为关。两处是不同开关；app-guide §1.3 把诊断页那项记作默认关，数据页那项未区分。
- 脚本新建表单比 app-guide 多：引擎（auto / jsc / webview）、二进制模式、脚本更新间隔、参数、调试、启用脚本；脚本类型有 event / rule / dns / cron。
- URL 重写的「类型」选项：HEADER / 302 / 307 / PROXY / DIRECT / TAILSCALE + REJECT 家族（app-guide 未列）。
- 头部重写表单：类型 http-request / http-response；行为 header-del / header-add / header-replace / header-replace-regex。
- 外观 › 颜色 页给出了整套主题色（hex），本机是用户自定义的浅粉主题；外观模式显示「深色」但画面是浅色调。
- 首页「全局路由」页结构：启用回退在顶部；设置分区里有「分组」「场景」两个子页。

## Clash 1.0.14 (178) — Clash Mi 装上之前的替代品

凌晨遍历时手机上找不到 Clash Mi（早上已装上，见下文「Clash Mi」一节）。Spotlight 搜「Clash Mi」「clashmi」「Mi」都没有这个 App。唯一的 mihomo 系客户端是 ProjectClash 的「Clash」1.0.14 (178)，内核 1.19.33。为了不让 Mihomo 这一侧空着，我按同样的只读规则遍历了它。**它不是简报指定的 App，不能拿来回写 Clash Mi 的 app-guide。** 清单在 `inventory/clash.json`（20 屏，221 行），截图在 `screens/clash/`。

当前配置 `<lan-host>(3)` 是实验配置，状态「未连接」，全程没有启动。

### 走到的地方

- 首页：出站模式卡（只记录）、代理（列表 + 一条 SS 节点的编辑表单）、规则。
- 配置中心（配置名 ⌄）：配置列表结构；当前配置 ⓘ → 配置详情。配置详情里进了「全局配置」（含「9 项在 iPhone 上不起作用」）、「DNS」、「入站」。**这一层就是简报说的「核心设置」**：每一项对应 Mihomo YAML 的一个顶层段，脚注写着「改动即时生效」，没有保存按钮。
- 工具 tab：整页结构。
- 更多 tab：按需求连接、VPN、客户端设置（含外部控制器）、外观、Geo 资源、存储空间、关于。

### 没走到的地方

| 入口 | 原因 |
| --- | --- |
| 启动；Spotlight 里的 启动 / 停止 / 切换 Clash 快捷指令 | 会连接或切换 |
| 配置行本体、出站模式三项、外部控制器三项、主题分段 | 点了就会切换 |
| 链接设置 | 内含订阅链接 |
| 编辑源码、查看生效中的配置 | 整份配置原文，含节点敏感值 |
| 域名嗅探、出站代理、代理集合、代理组、路由规则、规则集合、子规则、流量隧道、NTP、实验性配置 | 时间优先，只进了最关键的三段 |
| DNS 的「2 项在 iPhone 上不起作用」、入站「更多设置」后半段 | 时间优先 |
| 节点库、规则库、模块、自定义规则、覆写脚本 | 时间优先 |
| 规则「编辑」、按需求规则的 Connect / 编辑 / + | 编辑表单 |
| 全部更新、同步 Geo、检查 / 复制 / 导出 / 删除配置、清理 | 动作 |
| 活动、运行状况、外部资源、诊断收件箱 | 需要连接，或含访问记录 |
| 网络质量、STUN 与 NAT、DNS 查询 | 测试动作 |

### 敏感值处理

- `home-node-edit_1.png` 和 `home-node-edit_2.png`：服务器地址、端口、密码和加密方式这几行的值已涂黑。
- 「访问密钥」（secret）当前显示「无」，没有值要处理。外部控制器页不显示 Secret。

### 与 Clash Mi app-guide 的差异（不能直接回写，只作参考）

两个 App 的结构差得很远。下面这些只说明「Mihomo 客户端在 iOS 上还可能长这样」：

1. 底部 tab 是 首页 / 工具 / 更多，和 Surge 一样；Clash Mi 是主页加一串入口。
2. 没有「核心覆写 / 不覆写」这一层。配置详情直接编辑配置本身（「改动即时生效」），另外有「规则方案 / 自定义规则 / 覆写脚本」三项属于这份配置的本机覆写。
3. 「全局配置 › 9 项在 iPhone 上不起作用」：find-process-mode、routing-mark、interface-name、geo-auto-update、geo-update-interval、geodata-loader 等由 App 固定处理，写了也不生效。SubHub 如果写这些键，这里会明确标出不起作用。
4. VPN 页的「强制路由 / 包括所有网络 / 包括本地网络 / 包括 APNs / 包括蜂窝服务 / 排除 APNs 路由 / HomeKit 兼容」是 iOS VPN 参数，存在本机。HomeKit 兼容的说明里提到「配置里已设 tun.strict-route 时不必开」。
5. 入站页的路由各项都标着「在『VPN 与路由』里改」，但更多 tab 只有「VPN」入口，没找到名为「VPN 与路由」的页。
6. 客户端设置 › 下载身份 › 链接兼容性 默认「Clash」。它决定拉 SubHub 订阅时用哪个 UA，会影响 SubHub 按客户端识别输出。
7. 客户端设置 › 外部控制器默认「使用配置」，跟随配置里的 external-controller；另外两个选项「本机 / 局域网」会覆盖配置。
8. intent `clash_dns_enable`、`clash_dns_listen`、`clash_tun_enable`、`clash_tun_stack`、`clash_tun_auto_route`、`clash_tun_auto_detect_interface` 在看过的页里都没有对应行，可能被 App 固定处理了，没核对。

## Surge iOS 5.23.0 (Build 3867, SDK 27.1) — 已完成

当前配置 `sg3-b`（实验配置，不是 SubHub 生成的），VPN 未启动，全程没有启动。清单 `inventory/surge.json`：38 屏，244 行。

### 走到的地方

- 首页 › 通用：出站模式卡（只记录，不切换）、代理服务器（列表 + 一条 Shadowsocks 节点的表单）、代理规则、DNS 设置（含 Surge Private DDNS）、本地 DNS 映射、Surge Ponte。
- 首页 › 通用 › 更多设置 ›「高级」：网络优化、延迟测试、子网设置覆盖、GeoIP 数据库、IPv6、接管模式、Wi-Fi 访问组、远端控制器、HTTP API & Web 面板，以及「高级设置」整页（7 屏截图，22 个键）。
- 首页 › 捕获：捕获流量 › 设置、MitM › 配置（HTTPS 解密）、MitM › 主机名、数据包捕获 › 限制器。
- 首页 › 修改：重写规则菜单 → URL / Header / Body 重写（Body 进了一条 JQ 条目的表单），Mock（进了一条条目），脚本，模块。
- 工具 tab：整页结构。
- 更多 tab：整页结构，以及配置升级（向导）、始终开启、配置同步。

### 没走到的地方

| 入口 | 原因 |
| --- | --- |
| 配置名 ⌄（配置列表） | 点一行就会切换当前配置 |
| 启动 | 会启动 VPN |
| 出站模式三项、接管模式三项、主题卡片、配置同步三项 | 单选，点了就会切换 |
| 工具 › 当前状态 8 项 | 未启动时不可用（行是灰的） |
| 最近请求、捕获结果、已保存数据、路由表、日志 | 数据查看页，可能含访问记录 |
| 日志等级弹出菜单、UDP 回退行为 / IPv6 VIF / 屏蔽 QUIC 等弹出菜单 | 避免误选 |
| HTTP / SOCKS5 端口子页、网络优化的三个「开启」 | 输入页或只读，没有新内容 |
| 节点表单子页（代理类型、加密方式、Obfs、IPv4 & IPv6、Shadow TLS、通过另一个代理连接） | 子页是选项列表，时间优先 |
| 策略组表单 | 当前配置没有策略组 |
| 规则页 •••、模块行与 •••、新建 / 安装模块、调整生效顺序、审查修改后的配置 | 菜单或会启停模块 |
| 生成新的 CA、安装证书、导出 .crt / .p12、GeoIP 现在更新、接受分享邀请 | 动作 |
| 授权管理、已解锁的功能、密钥库 | 含账户或密钥 |
| 外观各项、警告信息、通知、动态资源、分析与提升、其他平台、帮助、关于各项 | 本机设置或外链，时间优先 |
| 远端控制器 › 云通知、iPerf、脚本编辑器 | 工具或动作页 |

### 退出方式的例外

- Surge Ponte、模块、数据包捕获 › 限制器这三页只有右上 ✓，没有 ✕。下拉和滚轮都关不掉，只能点 ✓ 退出。三页都没改任何项。
- 「高级设置」进入时弹「警告」，按钮只有「好的」，点了它（只是提示，不是授权）。
- 「配置升级」是全屏向导，用左上「取消」退出，没点「确认」。

### 敏感值处理

- `more-advanced-http-api.png`：HTTP API 密码在界面上是明文显示的，截图里已涂黑，清单写 `<redacted>`。
- `home-proxy-edit_1.png`：服务器地址、端口、加密方式和密码四行的值已涂黑。
- `capture-mitm_1.png`：CA 名称后面的 ID 已涂黑。
- 局域网地址（DNS 服务器、节点列表副标题、当前 Wi-Fi IP）是实验网段，没有涂黑。

### 与 app-guide 对不上的地方（供回写 skill）

1. **底部 tab**：现在只有 首页 / 工具 / 更多 三个。app-guide §1.1 里的「代理」tab 不存在了；代理服务器和策略组在 首页 › 通用 › 代理服务器。
2. **HTTP API & Web 面板**：app-guide 写的是「未记录」。界面上有 HTTP API 开关、端口、密码、允许由 Wi-Fi 控制、HTTPS、Web 面板，正好对应 intent `surge_http_api` / `surge_http_api_secret` / `surge_http_api_tls` / `surge_http_api_web_dashboard`。密码是明文显示的。
3. **远端控制器**：子页只有一个「远端控制器」开关，键名未知。
4. **修改 › HTTP 重写卡片**：除了「重写规则」，还有一个「Mock」按钮（Map Local，对应 intent `surge_map_local`）。app-guide §1.1 只写了 URL / Header / Body 重写。
5. **URL 重写页**：菜单项叫「URL 重写」，页标题却是「URL 重定向」，脚注是 Header 重写的文案。这是 App 自己的文案错位。
6. **更多 › 授权**：分组里有「授权管理」和「已解锁的功能」两行。app-guide 只写了后者。
7. **MitM › 配置（HTTPS 解密）**：页面上有 跳过服务端证书验证（intent `surge_mitm_skip_server_cert_verify`）、MITM over HTTP/2（`surge_mitm_h2`）和「自动屏蔽 QUIC」（默认开，键名未知）。intent `surge_mitm_tcp_connection` 在界面上找不到对应的行。
8. **节点表单里的「屏蔽 QUIC 流量」**（自动 / 开 / 关）是节点级参数。intent `surge_block_quic` 指的是 `[General]`，两者要区分。
9. **「在 DNS 失败时使用默认策略」**：SubHub 的 FINAL 行总是带 `dns-failed`，所以 SubHub 配置导入后这个开关应该显示为开。本次看到的「关」是实验配置的值。
10. **延迟测试 › 代理测试 URL**：SubHub 固定写 `https://cp.cloudflare.com/generate_204`，但 intent_registry 没有这一项。
11. **更多 › 关于**：页脚版本行是「Version 5.23.0 (Build 3867, SDK 27.1)」。
12. **配置升级向导**：卡片「Smart 策略组 · 已包含在更新订阅中」，「应用该更新」默认开。向导说明「自动调整对托管配置亦可生效」，确认后会把 url-test / load-balance 组改写成 smart。SubHub 写的 url-test 组会受影响，值得在 app-guide §2.8 里写明。

## replica

已做 Shadowrocket 配置编辑页、Surge 高级（顶部 + 滚到底）、Clash 全局配置、Clash Mi 核心设置。分数和已知差异见 README。Clash Mi 装上后补了「核心设置」复刻，共 5 屏。

tokens 全部按 1.5 px/pt 计算；早期笔记里的 1.54 已作废。2026-11-11 复核时改正了 tokens 里的几处数值，README 里列了清单。

## Clash Mi 1.0.31.1703（mihomo 1.19.32）— 已完成

首次启动按用户指示选了「无线局域网与蜂窝网络」。之后 App 直接进了核心设置，自己的「Your Privacy Comes First / Accept & Continue」页消失了，那个按钮没点到。新装状态：未导入配置、未连接，覆写方案是「内置-覆写」。

遍历了：

- 首页。
- 我的配置：空。
- 核心设置全部 21 行，以及 TUN、Geo RuleSet、分流模板、覆写、局域网设备接入、DNS、NTP、TLS、嗅探 9 个子页。
- 应用设置。
- 关于。

没遍历及原因：

| 入口 | 原因 |
| --- | --- |
| 核心设置右上 📄 | 显示生成的配置原文，含 Secret |
| 重置（核心设置 / 应用设置） | 动作 |
| Pprof | 调试 |
| 分流模板的 3 个子页；DNS 的 hosts、fake-ip 过滤与各解析服务器子页 | 时间优先 |
| 覆写列表行本体、☁︎ / + | 点按即切换覆写方案或导入 |
| 核心日志、备份与同步、帮助 | 日志含访问记录；备份可能涉及账户；帮助是外链 |
| 首页「未连接」开关、分流模式三段 | 连接 VPN / 切换路由模式 |

涂黑：`core-settings_1.png` 的 Secret 值。inventory 里写成 `<redacted>`。

和 SubHub 的关系：

- 核心设置是 App 本机的一层覆写，行一律记为 layer=app。
- SubHub 订阅也写了同名字段的，`subhub`=只在手机本机，note 里写明会被盖掉。
- app-guide 里有实验证据的（哪些项在「内置-不覆写」时仍压过订阅）抄进了 note，带 E-M 编号。

### 与 app-guide 对不上的地方

- **首次启动**：app-guide 只记了系统「使用无线数据」弹窗，没记 App 自己的「Your Privacy Comes First / Accept & Continue」页。这次那一页在选完系统弹窗后自己消失了。
- **局域网设备接入 › IP**：app-guide 写 `*`，新装这台显示为空（下拉）。
- **app-guide 没提的行**：
  - 核心设置的 Pprof Address / Pprof。
  - Geo RuleSet 子页：更新间隔 2 d、使用代理下载、GeoSite / GeoIp 地址。
  - DNS 页：「代理 / 直连 域名解析服务器」「Fallback GeoIp 代码」。
- **不是每行都能单选覆写**：app-guide 说「每行可单独选覆写 / 不覆写」。实际上只有下拉类的行有「不覆写」选项；TUN / DNS / 局域网 / NTP / TLS / 嗅探是整页一个「覆写」开关；外部控制、Secret、混合代理端口没有覆写开关。

