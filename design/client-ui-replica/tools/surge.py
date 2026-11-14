from common import *
P="profile";A="app";X="action"
S=[]
H=["首页 tab"]
G=H+["通用"]
ADV=G+["更多设置 ›（高级）"]
SHEET={"left":"✕","right":"✓（保存）"}
PUSH={"left":"返回"}
iv=lambda k:f"intent {k}"

# ---------- 首页 ----------
S.append(screen("home-general",G,"sg3-b（首页 · 通用）",{"left":"配置名 sg3-b ⌄（切换配置）","right":"启动"},[
 group("出站模式（卡片）",[
  row("直接连接","segmented",None,layer=A,subhub="device",note="单选；按简报不切换"),
  row("全局代理","segmented",None,layer=A,subhub="device"),
  row("规则模式","segmented","✓（副标题：使用规则系统决定如何处理请求）",layer=A,subhub="device"),
  row("代理服务器","button",None,"home-proxies",layer=P,subhub="writes",maps_to="[Proxy] / [Proxy Group]"),
  row("代理规则","button",None,"home-rules",layer=P,subhub="writes",maps_to="[Rule]")]),
 group("DNS（卡片）",[
  row("DNS 设置","button",None,"home-dns",layer=P,subhub="writes",maps_to=iv("surge_dns_server")+" / "+iv("surge_encrypted_dns_server")),
  row("本地 DNS 映射","button",None,"home-local-dns",layer=P,subhub="writes",maps_to=iv("surge_host_records"))],
  "覆盖系统 DNS 设置，加密 DNS 和配置本地 DNS 映射记录"),
 group("Surge Ponte（卡片）",[row("配置","button",None,"home-ponte",layer=A,subhub="none")],
  "Surge Ponte 是运行 Surge Mac, iOS 和 tvOS 的设备之间的私有 Mesh 网络"),
 group(None,[row("更多设置 ›","link",None,"more-advanced",layer=A,subhub="na")])],
 ["home-general_1.png","home-general_2.png"],
 [("配置名 ⌄","打开配置列表，点一行即切换当前配置；按简报不进"),("启动","会启动 VPN")],kind="home",
 note="顶部三段：通用 / 捕获 / 修改；卡片式布局，不是 iOS 分组列表"))

S.append(screen("home-capture",H+["捕获"],"sg3-b（首页 · 捕获）",{"left":"配置名 ⌄","right":"启动"},[
 group("捕获流量（卡片）",[row("捕获流量","toggle","关",layer=A,subhub="device"),row("最近请求","button",None,layer=A,subhub="na"),row("设置","button",None,"capture-settings",layer=A,subhub="device")],"捕获 HTTP 请求与响应数据并保存，也可以查看 TCP 和 UDP 会话"),
 group("MitM（卡片）",[row("MitM","toggle","关",layer=A,subhub="device",note="主开关；配置里的 [MITM] 段不含该开关"),row("配置","button",None,"capture-mitm",layer=P,subhub="partial",maps_to="[MITM]"),row("主机名","button",None,"capture-mitm-hosts",layer=P,subhub="writes",maps_to=iv("surge_mitm_hostname"))],"使用中间人攻击（MitM）解密 HTTPS 流量，以查看其内容和使用高级功能"),
 group("数据包捕获（卡片）",[row("数据包捕获","toggle","关",layer=A,subhub="device"),row("捕获结果","button",None,layer=A,subhub="na"),row("限制器","button",None,"capture-pcap-limiter",layer=A,subhub="device")],"捕获网络层 TCP/UDP/ICMP 数据包供查看和分析")],
 ["home-capture.png"],[("最近请求 / 捕获结果","数据查看页，含访问记录，不进")],kind="home"))

S.append(screen("home-modify",H+["修改"],"sg3-b（首页 · 修改）",{"left":"配置名 ⌄","right":"启动"},[
 group("HTTP 重写（卡片）",[row("HTTP 重写","toggle","开",layer=A,subhub="device"),row("Mock","button",None,"modify-mock",layer=P,subhub="writes",maps_to=iv("surge_map_local")),row("重写规则","menu",None,"modify-rewrite-menu",layer=P,subhub="writes")],"重定向 HTTP 请求或者修改请求或响应的 Header 和 Body"),
 group("脚本（卡片）",[row("脚本","toggle","关",layer=A,subhub="device"),row("编辑器","button",None,layer=A,subhub="na"),row("脚本","button",None,"modify-scripts",layer=P,subhub="none",maps_to="[Script]",note="Surge 输出不写 [Script]")],"使用 JavaScript 扩展 Surge 的各项功能，或修改网络请求与响应"),
 group("模块（卡片）",[row("模块","button",None,"modify-modules",layer=A,subhub="device")],"模块是一系列设置的集合，可用于覆盖当前配置的部分设定")],
 ["home-modify.png"],[("编辑器","脚本编辑器，不进")],kind="home"))

S.append(screen("modify-rewrite-menu",H+["修改","重写规则"],"重写规则（弹出菜单）",{},[group("重写规则",[
 row("URL 重写","menu-item",None,"modify-url-rewrite",layer=P,subhub="writes",maps_to=iv("surge_url_rewrite")),
 row("Header 重写","menu-item",None,"modify-header-rewrite",layer=P,subhub="writes",maps_to=iv("surge_header_rewrite")),
 row("Body 重写","menu-item",None,"modify-body-rewrite",layer=P,subhub="writes",maps_to=iv("surge_body_rewrite")+" / "+iv("surge_jq_body_rewrite"))])],["modify-rewrite-menu.png"],kind="menu"))
S.append(screen("modify-url-rewrite",H+["修改","重写规则","URL 重写"],"URL 重定向",SHEET,[
 group(None,[row("新增…","action",layer=X,subhub="na")],"Surge 可以修改发送到服务器的 HTTP Header，以及修改返回响应的 Header。"),
 group(None,[row("无项目","placeholder",layer=P,subhub="writes",maps_to=iv("surge_url_rewrite"))]),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["modify-url-rewrite.png"],[("新增…","进新建表单")],kind="list",
 note="菜单叫「URL 重写」，页标题是「URL 重定向」，脚注却是 Header 重写的文案（App 原文如此）"))
S.append(screen("modify-header-rewrite",H+["修改","重写规则","Header 重写"],"Header 重写",SHEET,[
 group(None,[row("新增…","action",layer=X,subhub="na")],"Surge 可以修改发送到服务器的 HTTP Header，以及修改返回响应的 Header。"),
 group(None,[row("无项目","placeholder",layer=P,subhub="writes",maps_to=iv("surge_header_rewrite"))]),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["modify-header-rewrite.png"],[("新增…","进新建表单")],kind="list"))
S.append(screen("modify-body-rewrite",H+["修改","重写规则","Body 重写"],"Body 重写",SHEET,[
 group(None,[row("新增…","action",layer=X,subhub="na")],"Surge 可以重写 HTTP 请求或响应的 Body，用正则表达式替换原始内容。如果你需要进行更灵活的修改，请使用脚本。"),
 group(None,[row("<URL 正则>","disclosure","副标题：http-response-jq <jq 表达式>","modify-body-rewrite-edit",layer=P,subhub="writes",maps_to=iv("surge_jq_body_rewrite")),
  row("<URL 正则>","disclosure","副标题：http-response <正则> <替换>",layer=P,subhub="writes",maps_to=iv("surge_body_rewrite"))],"在任意一行上长按可调整顺序。"),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["modify-body-rewrite.png"],kind="list",note="当前是实验配置的两条 lab.test 规则"))
S.append(screen("modify-body-rewrite-edit",H+["修改","重写规则","Body 重写","条目"],"Body 重写",SHEET,[
 group("模式",[row("HTTP 方向","segmented","Request / Response（选中 Response）",layer=P,subhub="writes",maps_to=iv("surge_jq_body_rewrite")),
  row("修改模式","segmented","Text Regex / JSON JQ（选中 JSON JQ）",layer=P,subhub="writes",maps_to=iv("surge_jq_body_rewrite"))]),
 group("URL 正则表达式",[row("URL 正则","textfield","<URL 正则>",layer=P,subhub="writes")]),
 group(None,[row("JQ 表达式","textfield","<jq 表达式>",layer=P,subhub="writes")],"使用 JQ 表达式操作 JSON 数据，如果 Body 并非 JSON 会导致请求失败。请搜索 JQ 项目文档以了解表达式编写方式。")],
 ["modify-body-rewrite-edit.png"],kind="form",note="Text Regex 模式下的字段未看（要切分段）"))
S.append(screen("modify-mock",H+["修改","Mock"],"Mock",SHEET,[
 group(None,[row("新增…","action",layer=X,subhub="na")],"您可以模拟 API 服务器并返回静态响应。此功能也可称为 Map Local 或 API Mocking。如果你想动态返回响应，请使用脚本。"),
 group(None,[row("<URL 正则>","disclosure","副标题：数据内容","modify-mock-edit",layer=P,subhub="writes",maps_to=iv("surge_map_local"))],"在任意一行上长按可调整顺序。"),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["modify-mock.png"],kind="list"))
S.append(screen("modify-mock-edit",H+["修改","Mock","条目"],"Mock",SHEET,[
 group("URL 正则表达式",[row("URL 正则","textfield","<URL 正则>",layer=P,subhub="writes",maps_to=iv("surge_map_local"))]),
 group("数据源",[row("数据类型","popup","文本 ⌃⌄",layer=P,subhub="writes",maps_to=iv("surge_map_local"))]),
 group(None,[row("数据内容","textfield","<文本>",layer=P,subhub="writes")]),
 group(None,[row("自定义状态码","textfield","占位 200",layer=P,subhub="unverified"),row("自定义响应 Header","disclosure",layer=P,subhub="unverified")])],
 ["modify-mock-edit.png"],[("数据类型其他选项 / 自定义响应 Header","弹出菜单与子页未进")],kind="form"))
S.append(screen("modify-scripts",H+["修改","脚本"],"脚本",SHEET,[
 group(None,[row("新增…","action",layer=X,subhub="na")],"使用 JavaScript 扩展 Surge 的功能，查看手册以获得更多信息。"),
 group(None,[row("无项目","placeholder",layer=P,subhub="none",maps_to="[Script]")]),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["modify-scripts.png"],[("新增…","进新建表单")],kind="list"))
S.append(screen("modify-modules",H+["修改","模块"],"模块",{"right":"✓（完成，唯一按钮）"},[
 group("官方",[row("Enhancements ✓认证","disclosure-group",layer=A,subhub="none",note="可折叠"),row("Quirks ✓认证","disclosure-group",layer=A,subhub="none")]),
 group("本地与已安装",[row("未分类","disclosure-group","展开",layer=A,subhub="na"),
  row("<模块名>","toggle-row","左侧 ✓ = 已启用；副标题为模块描述；右侧 •••",layer=A,subhub="device",note="点行即切换启用，未点")]),
 group(None,[row("新建本地模块…","action",layer=X,subhub="na"),row("安装新模块…","action",layer=X,subhub="na"),row("调整生效顺序","disclosure",layer=A,subhub="device"),row("审查修改后的配置","disclosure",layer=A,subhub="na")]),
 group(None,[row("在线手册…","link",layer=X,subhub="na")],"模块是一系列设置的集合，可用于覆盖当前配置的部分设定，有非常多的使用场景：• 微调不可编辑的配置的设定，如托管配置和团队配置。• 快捷的在不同工作环境中切换，比如临时开启对所有域名的 MitM 并调整过滤器。• 使用他人编写的模块以完成某些特定任务，比如，你的同事可以编写一个模块将应用的 API 请求重定向至测试服务器。• 如果你在多个设备间使用了同一份配置，有可能需要根据设备的使用场景进行微调。模块的开启状态是保存于当前设备的，可以用于在不同设备间的差异性修改。")],
 ["modify-modules.png","modify-modules_2.png"],[("模块行 / •••","点行即启停模块"),("新建 / 安装 / 调整顺序 / 审查","动作或子页，未进")],kind="list",
 note="SubHub 不产出 Surge 模块；脚注明说模块启用状态存于本机"))

S.append(screen("home-proxies",G+["代理服务器"],"代理服务器",SHEET,[
 group("代理",[row("<节点名>","disclosure","蓝色徽标「Shadowsocks」+ 服务器地址","home-proxy-edit",layer=P,subhub="writes",maps_to="[Proxy]",note="只记一条的结构"),row("添加代理…","action",layer=X,subhub="na")]),
 group("策略组",[row("新的策略组…","action",layer=X,subhub="na")],"在任意一行上长按可调整顺序。"),
 group("选项",[row("UDP 回退行为","popup","阻止 ⌃⌄",layer=P,subhub="writes",maps_to="[General] udp-policy-not-supported-behaviour",note="SubHub 固定写 REJECT；键名来自 app-guide，intent 未列")],"并非所有代理服务器都支持 UDP 转发，当一个 UDP 会话尝试使用一个不支持 UDP 转发的代理服务器时，Surge 默认会回退至直连。可修改为阻止以避免潜在的隐私泄漏隐患。")],
 ["home-proxies.png"],[("添加代理… / 新的策略组…","新建表单")],kind="list",note="当前配置 sg3-b 没有策略组，看不到策略组行的结构"))
S.append(screen("home-proxy-edit",G+["代理服务器","<节点>"],"代理",SHEET,[
 group("名称",[row("名称","textfield","<节点名>",layer=P,subhub="writes",maps_to="[Proxy] 名称")]),
 group(None,[row("代理类型","disclosure","Shadowsocks",layer=P,subhub="writes",maps_to="[Proxy] 协议")]),
 group("服务器信息",[row("服务器地址","textfield","<redacted>",layer=P,subhub="writes"),row("端口号","textfield","<redacted>",layer=P,subhub="writes"),row("加密方式","disclosure","<redacted>",layer=P,subhub="writes"),row("密码","textfield","<redacted>（掩码）",layer=P,subhub="writes"),row("UDP Relay","toggle","开",layer=P,subhub="writes",note="udp-relay 参数")]),
 group("选项",[row("Obfs","disclosure","Disabled",layer=P,subhub="unverified"),row("Obfs Host","textfield","占位 默认",layer=P,subhub="unverified")]),
 group(None,[row("TCP Fast Open (Experimental)","toggle","关",layer=P,subhub="unverified"),row("IPv4 & IPv6","disclosure","双栈",layer=P,subhub="unverified")],"该选项仅影响和代理服务器间的连接，因此仅当服务器主机名为域名时有意义。若配置了跳板代理，由于在跳板远端进行 DNS 解析，该选项无效。"),
 group(None,[row("屏蔽 QUIC 流量","popup","自动 ⌃⌄",layer=P,subhub="unverified",candidate="block-quic（节点参数；intent surge_block_quic 指 [General]）")],"通过代理进行 QUIC 流量转发可能产生性能问题，开启该选项将阻止 QUIC 流量，以使得客户端回退至传统 HTTPS/TCP 协议。"),
 group(None,[row("Shadow TLS Version","disclosure","Disabled",layer=P,subhub="unverified")],"Shadow TLS 是一个流量混淆插件，可以将代理流量伪装为真实的 TLS 流量。详细信息请查看该项目的 GitHub 页面说明。"),
 group(None,[row("覆盖全局测试 URL","textfield","占位 http(s)://",layer=P,subhub="unverified")]),
 group(None,[row("通过另一个代理连接","disclosure",layer=P,subhub="unverified")],"使用一个代理连接另一个代理，该功能又被称为代理链或跳板代理。")],
 ["home-proxy-edit_1.png","home-proxy-edit_2.png","home-proxy-edit_3.png"],[("代理类型 / 加密方式 / Obfs / IPv4 & IPv6 / Shadow TLS / 通过另一个代理连接","子页未进")],kind="form",
 note="服务器地址、端口、加密方式、密码在截图里已涂黑；字段随代理类型变化，这里只是 Shadowsocks"))
S.append(screen("home-rules",G+["代理规则"],"规则",{"left":"✕","right":"•••  ✓（保存）"},[
 group(None,[row("新增…","action",layer=X,subhub="na")]),
 group(None,[row("<规则值>","disclosure","徽标 DOMAIN / DOMAIN-SUFFIX 等 + 策略名",layer=P,subhub="writes",maps_to="[Rule]"),row("默认策略","disclosure","绿色徽标 FINAL + 策略名",layer=P,subhub="writes",maps_to="[Rule] FINAL（app-guide）")]),
 group("选项",[row("在 DNS 失败时使用默认策略","toggle","关",layer=P,subhub="writes",maps_to="[Rule] FINAL,…,dns-failed",note="SubHub 的 FINAL 行带 dns-failed，导入后应显示为开")],"如果 DNS 查找失败，请使用 FINAL 规则，否则请求将失败。"),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["home-rules.png"],[("•••","菜单未开"),("新增… / 规则行","表单")],kind="list"))
S.append(screen("home-dns",G+["DNS 设置"],"DNS",SHEET,[
 group("DNS 服务器",[row("使用系统 DNS 服务器","segmented",layer=P,subhub="writes",maps_to=iv("surge_dns_server")),row("使用自定义 DNS 服务器","segmented","✓",layer=P,subhub="writes",maps_to=iv("surge_dns_server")),row("混合系统和自定义 DNS 服务器","segmented",layer=P,subhub="writes",maps_to=iv("surge_dns_server"))],"你可以使用该选项强制替代系统的 DNS 服务器设置，使用 , 分隔多个服务器。为了性能考虑 Surge 会向所有服务器并发进行请求。"),
 group("自定义 DNS 服务器",[row("<DNS 地址>","list-item","左侧红色删除圆钮",layer=P,subhub="writes",maps_to=iv("surge_dns_server")),row("增加服务器…","action",layer=X,subhub="na")]),
 group("加密 DNS",[row("加密 DNS","textfield","空（占位）",layer=P,subhub="writes",maps_to=iv("surge_encrypted_dns_server"))],"如果在此配置了 DNS 服务器，传统 DNS 将仅用于连通性测试和解析服务器 URL 中的域名。\n\n支持的协议：\n• DNS over HTTPS: https://example.com\n• DNS over HTTP/3: h3://example.com\n• DNS over QUIC: quic://example.com\n• DNS over TLS: tls://example.com\n• DNS over TCP: tcp://example.com\n\nDNS over TCP 未加密，默认使用 53 端口，请仅用于可信服务器。"),
 group(None,[row("Surge Private DDNS","disclosure",None,"home-dns-ddns",layer=A,subhub="none"),row("代理请求本地 DNS 映射","toggle","关",layer=P,subhub="none",maps_to="[General] use-local-host-item-for-proxy")],"默认情况下，使用代理策略时域名解析一定在远端服务器上进行。\n开启该选项后，如果访问的域名配置有本地 DNS 映射，Surge 将使用本地 IP 地址进行请求，不在远端进行解析。\n仅对配置了 IP 地址的本地 DNS 映射生效。")],
 ["home-dns_1.png","home-dns_2.png"],kind="form"))
S.append(screen("home-dns-ddns",G+["DNS 设置","Surge Private DDNS"],"Surge DDNS",PUSH,[
 group(None,[row("解析 Surge DDNS 域名","toggle","关",layer=A,subhub="none")],"Surge Mac 可将其外部 IP 地址与 .sgddns 域名绑定，你可以在其他设备使用 Surge iOS 或 Surge Mac 的设备上访问该域名。数据由 iCloud 进行同步，不可在公网访问该域名。（脚注按截图转写，个别字可能有出入）")],["home-dns-ddns.png"]))
S.append(screen("home-local-dns",G+["本地 DNS 映射"],"本地 DNS 映射",SHEET,[
 group(None,[row("新增…","action",layer=X,subhub="na")],"该功能基本等同于 /etc/hosts。"),
 group(None,[row("无项目","placeholder",layer=P,subhub="writes",maps_to=iv("surge_host_records"))]),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["home-local-dns.png"],[("新增…","进新建表单")],kind="list"))
S.append(screen("home-ponte",G+["Surge Ponte","配置"],"Surge Ponte",{"right":"✓（完成，唯一按钮）"},[
 group("已注册设备",[row("没有已注册的设备","placeholder",layer=A,subhub="none")],"Surge Ponte 是你在运行 Surge Mac 与 iOS 设备间的私有网状网络。\n• 零配置需求。\n• Surge 会自动选择最适合的通道建立连接。\n• 始终端到端加密，并且加密密钥通过你的 iCloud 同步。\n• 除非你选择代理服务器，否则你的数据不会经过第三方服务器。"),
 group(None,[row("使用代理","disclosure",layer=A,subhub="none")],"如果已在远端设备上配置使用代理进行 NAT 穿透，最好选择与之相同的代理，但这并非必须。请阅读手册以了解更多信息。"),
 group(None,[row("接受分享邀请…","action",layer=X,subhub="na")],"默认情况下你只可以访问自己 iCloud 下的 Ponte 设备。通过分享功能，可以访问其他 iCloud 下注册的 Ponte 设备，请在先对应的 Surge Mac 上获取确认码。"),
 group(None,[row("在线手册…","link",layer=X,subhub="na")]),
 group(None,[row("调试信息","toggle","关",layer=A,subhub="device")],"开启该选项后，每次在 Ponte 进行连接时，Surge 会使用推送消息显示 Ponte 的连接状态。")],
 ["home-ponte.png"],[("使用代理","子页未进"),("接受分享邀请… / 在线手册…","动作或外链")],note="打开时先转圈约 3 秒；只有 ✓ 没有 ✕，下拉关不掉，只能点 ✓ 退出（未改任何项）"))

# ---------- 捕获 ----------
S.append(screen("capture-settings",H+["捕获","捕获流量 › 设置"],"请求记录",{"left":"✕","right":"保存"},[
 group("捕获过滤器",[row("内存捕获过滤器","disclosure",layer=A,subhub="device"),row("磁盘上的 HTTP 捕获过滤器","disclosure",layer=A,subhub="device")],"Surge 有两种请求记录模式：\n• 内存记录：Surge 总是会在内存中保留最近 50 条请求的摘要，供随时查看。\n• HTTP 捕获：将请求摘要和 HTTP 请求的 Body 存储到磁盘中。该模式下性能开销严重，请仅在需要时开启。\n可为这两种模式分别配置不同的过滤器，将在模式切换时自动切换。"),
 group("磁盘上的 HTTP 捕获限制器",[row("时间限制","popup","3 分钟 ⌃⌄",layer=A,subhub="device"),row("文件大小限制","popup","50 MB ⌃⌄",layer=A,subhub="device"),row("数量限制","popup","100 请求 ⌃⌄",layer=A,subhub="device")],"在达到上述限制之一时，自动停止本次 HTTP 捕获会话。"),
 group("磁盘上的 HTTP 捕获 MITM 覆写",[row("自动开启 MITM","toggle","关",layer=A,subhub="device"),row("MITM 主机名","disclosure","（灰，未启用）",layer=A,subhub="device")],"在 HTTP 捕获功能期间，对额外的主机名开启 MITM 功能（若已配置 CA），生效期间可无视 MITM 主开关。")],
 ["capture-settings.png"],[("两个过滤器子页","未进")],kind="form",note="右上是文字按钮「保存」而不是 ✓"))
S.append(screen("capture-mitm",H+["捕获","MitM › 配置"],"HTTPS 解密",SHEET,[
 group("证书",[row("<CA 名称>","readonly","Surge Generated CA <redacted>；副标题「未被系统信任」",layer=A,subhub="device",note="证书图标；ID 已涂黑")]),
 group(None,[row("生成新的 CA 证书","disclosure",layer=X,subhub="na")],"你也可以使用自己的 CA 证书，请将证书转化为 Base64 编码的 PKCS #12 格式，使用文本编辑模式填入。"),
 group(None,[row("安装证书","disclosure",layer=X,subhub="na")],"安装后，请在设置 > 通用 > 关于 > 证书信任设置 中启动该证书。"),
 group("选项",[row("跳过服务端证书验证","toggle","关",layer=P,subhub="writes",maps_to=iv("surge_mitm_skip_server_cert_verify")),row("MITM over HTTP/2","toggle","关",layer=P,subhub="writes",maps_to=iv("surge_mitm_h2"))],"使用 HTTP/2 协议进行 MITM 解密，可在高并发下优化性能。"),
 group(None,[row("自动屏蔽 QUIC","toggle","开",layer=P,subhub="none")],"当 QUIC 连接（即 HTTP/3）命中 MITM 主机名列表时，自动阻止该 QUIC 连接，使得连接回退至 HTTP/2 或 HTTP/1.1，以使得其可被 MITM。"),
 group(None,[row("将证书导出至 .crt 文件","disclosure",layer=X,subhub="na"),row("将证书导出至 .p12 文件","disclosure",layer=X,subhub="na")])],
 ["capture-mitm_1.png","capture-mitm_2.png"],[("生成新的 CA / 安装证书 / 导出","动作，会改证书或导出文件")],kind="form",
 note="CA 本身（ca-p12 / ca-passphrase）SubHub 不写，只在本机；intent surge_mitm_tcp_connection 在界面没找到对应行"))
S.append(screen("capture-mitm-hosts",H+["捕获","MitM › 主机名"],"MITM",SHEET,[
 group(None,[row("新增…","action",layer=X,subhub="na")],"Surge 仅会解密这里指定的主机名的请求。\n\n•可使用通配符 * 和 ?\n•可使用前缀 - 将特定主机名排除\n•默认解密发往 443 端口的请求；其他端口上嗅探到 SNI 匹配的 TLS 请求同样会被解密\n  •可使用后缀 :port 仅解密特定端口\n  •可使用后缀 :0 解密所有端口\n查看手册获取更多信息\n\niOS 系统和某些应用有严格的安全策略，仅信任某些特定的证书，对这些域名启动解密可能导致问题，如 *.apple.com, *.icloud.com。"),
 group(None,[row("无项目","placeholder",layer=P,subhub="writes",maps_to=iv("surge_mitm_hostname"))]),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],["capture-mitm-hosts.png"],kind="list"))
S.append(screen("capture-pcap-limiter",H+["捕获","数据包捕获 › 限制器"],"限制器",{"right":"✓（完成，唯一按钮）"},[
 group(None,[row("数据包类型","disclosure","全部（默认）",layer=A,subhub="device")]),
 group(None,[row("时间限制","disclosure","3 分钟（默认）",layer=A,subhub="device"),row("文件大小限制","disclosure","1 MB（默认）",layer=A,subhub="device"),row("数据包数量限制","disclosure",layer=A,subhub="device")],"如果已开始数据包捕获，设置将对下次捕获生效。")],
 ["capture-pcap-limiter.png"],[("各子页","未进")],note="只有 ✓，用 ✓ 退出（未改任何项）"))

# ---------- 更多设置（高级） ----------
S.append(screen("more-advanced",ADV,"高级",SHEET,[
 group("通用",[row("网络优化","disclosure",None,"more-advanced-netopt",layer=P,subhub="none"),row("延迟测试","disclosure",None,"more-advanced-latency",layer=P,subhub="partial"),row("子网设置覆盖","disclosure",None,"more-advanced-subnet",layer=P,subhub="none"),row("GeoIP 数据库","disclosure",None,"more-advanced-geoip",layer=P,subhub="none"),row("IPv6","disclosure",None,"more-advanced-ipv6",layer=P,subhub="partial"),row("接管模式","disclosure",None,"more-advanced-takeover",layer=A,subhub="unverified")]),
 group("Wi-Fi 访问",[row("允许 Wi-Fi 访问","toggle","关；副标题「当前 Wi-Fi IP: <局域网 IP>」",layer=P,subhub="none",maps_to="[General] allow-wifi-access（app-guide 推测）"),row("允许个人热点访问","toggle","关",layer=P,subhub="none"),row("HTTP 代理服务端口","disclosure","6152",layer=P,subhub="none"),row("SOCKS5 代理服务端口","disclosure","6153",layer=P,subhub="none")],"Surge 可以作为一个标准的 HTTP/SOCKS5 代理服务器向 Wi-Fi 网络下的其他设备提供服务器。默认 HTTP 端口号：6152，SOCKS5 端口号：6153"),
 group("远程控制",[row("远端控制器","disclosure",None,"more-advanced-remote-controller",layer=P,subhub="none"),row("HTTP API & Web 面板","disclosure",None,"more-advanced-http-api",layer=P,subhub="writes",maps_to=iv("surge_http_api"))],"允许远程 Surge 面板或 Surge CLI 进行管理控制。"),
 group("高级",[row("日志等级","popup","notify ⌃⌄",layer=P,subhub="writes",maps_to=iv("surge_loglevel"),note="弹出菜单未打开"),row("高级设置","disclosure",None,"more-advanced-advset",layer=P,subhub="partial")])],
 ["more-advanced_1.png","more-advanced_2.png"],[("HTTP / SOCKS5 端口子页","输入页，未进"),("日志等级菜单","避免误选")],kind="form"))
S.append(screen("more-advanced-remote-controller",ADV+["远端控制器"],"远端控制器",SHEET,[
 group(None,[row("远端控制器","toggle","关",layer=P,subhub="none")],"允许远程 Surge 面板或 Surge CLI 进行管理控制。")],["more-advanced-remote-controller.png"]))
S.append(screen("more-advanced-http-api",ADV+["HTTP API & Web 面板"],"HTTP API & Web 面板",SHEET,[
 group(None,[row("HTTP API","toggle","开",layer=P,subhub="writes",maps_to=iv("surge_http_api"))],"让另一个 App 或者设备通过 HTTP API 控制 Surge 功能。"),
 group(None,[row("端口","textfield","6171",layer=P,subhub="writes",maps_to=iv("surge_http_api")),row("密码","textfield","<redacted>",layer=P,subhub="writes",maps_to=iv("surge_http_api_secret"),note="界面明文显示；截图已涂黑")]),
 group(None,[row("允许由 Wi-Fi 控制","toggle","开",layer=P,subhub="writes",maps_to=iv("surge_http_api"),note="对应 http-api 监听地址 0.0.0.0 / 127.0.0.1（推断）")],"默认仅允许本地程序访问 HTTP API，开启后将允许 Wi-Fi 网络访问。"),
 group(None,[row("HTTPS","toggle","关",layer=P,subhub="writes",maps_to=iv("surge_http_api_tls"))],"使用 HTTPS 替代 HTTP 协议。需要先配置 MITM 的 CA 证书，同时需要在客户端设备上手动安装并信任 CA 证书。"),
 group(None,[row("Web 面板","toggle","关",layer=P,subhub="writes",maps_to=iv("surge_http_api_web_dashboard"))],"开启该选项后可以通过浏览器控制 Surge。"),
 group(None,[row("API 在线手册…","link",layer=X,subhub="na")])],
 ["more-advanced-http-api.png"],[("API 在线手册…","外链")],kind="form",note="SubHub 只在 lazycat profile 且用户填了 http-api 时写这四项"))
S.append(screen("more-advanced-netopt",ADV+["网络优化"],"网络优化",PUSH,[
 group(None,[row("并发 DNS 查询","readonly","开启",layer=P,subhub="none",note="app-guide：只读，不可关闭")],"Surge 会向所有 DNS 服务器并发进行请求，并使用最快的响应结果。"),
 group(None,[row("Optimistic DNS","readonly","开启",layer=P,subhub="none")],"Surge 将沿用已过期的 DNS 结果缓存，同时进行新的 DNS 查询。当域名配置了过短的 TTL 时可有效减少不必要的等待时间。"),
 group(None,[row("TCP CDN 优化","readonly","开启",layer=P,subhub="none")],"如果域名包含多个 A/AAAA 记录，Surge 将并发向所有地址发起连接，最后选择速度最快的连接。"),
 group(None,[row("增强版 Wi-Fi 助理","toggle","关",layer=P,subhub="none",maps_to="[General] wifi-assist")],"Surge 会在 Wi-Fi 网络不佳时尝试使用数据网络建立连接。\n该功能将对所有 TCP 连接生效，请仅当使用不限量的数据流量套餐时开启。"),
 group(None,[row("混合网络","toggle","关",layer=P,subhub="none",maps_to="[General] all-hybrid")],"无论 Wi-Fi 信号如何，总是尝试并发使用 Wi-Fi 和数据网络建立连接。\n该选项可显著改善在弱 Wi-Fi 和网络切换时的网络体验。\n该选项对所有 TCP 连接和 DNS 查询生效。请仅当使用不限量的数据流量套餐时开启。"),
 group(None,[row("游戏优化","toggle","开",layer=P,subhub="none",maps_to="[General] udp-priority")],"开启后将在系统负载非常高，数据包处理出现延迟时，优先处理 UDP 数据包。")],
 ["more-advanced-netopt.png","more-advanced-netopt_2.png"],[("三个「开启」子页","选项页，未进")],
 note="layer 记为 profile 是按 Surge 惯例（[General] 键），未逐项核对是否存本机"))
S.append(screen("more-advanced-latency",ADV+["延迟测试"],"延迟测试",SHEET,[
 group("互联网测试 URL",[row("互联网测试 URL","textfield","<URL>",layer=P,subhub="none",maps_to="[General] internet-test-url")],"使用网络诊断功能时访问的 URL。"),
 group("代理测试 URL",[row("代理测试 URL","textfield","<URL>",layer=P,subhub="writes",maps_to="[General] proxy-test-url",note="SubHub 固定写 https://cp.cloudflare.com/generate_204；intent 未列")],"测试代理策略时的 URL。"),
 group(None,[row("测试超时（秒）","textfield","3",layer=P,subhub="none",maps_to="[General] test-timeout")],"Surge 将向该 URL 发送一个 HTTP HEAD 请求。测试只关心是否收到了返回数据，并不关心数据内容。仅支持 http:// 协议。")],
 ["more-advanced-latency.png"],kind="form",note="当前值是实验配置的 lab.test 地址"))
S.append(screen("more-advanced-subnet",ADV+["子网设置覆盖"],"子网设置覆盖",PUSH,[
 group(None,[row("新增子网设置…","action",layer=X,subhub="na")],"你可以在特定网络下覆盖部分设置或临时禁用 Surge。"),
 group(None,[row("无项目","placeholder",layer=P,subhub="none",maps_to="[Subnet Settings]")],"在任意一行上长按可调整顺序。")],["more-advanced-subnet.png"],[("新增子网设置…","新建表单")],kind="list"))
S.append(screen("more-advanced-geoip",ADV+["GeoIP 数据库"],"GeoIP 数据库",PUSH,[
 group("GeoIP 数据库",[row("最后更新","readonly","<日期时间>",layer=A,subhub="na"),row("现在更新…","action",layer=X,subhub="na")],"Surge 使用由 MaxMind 创建的 GeoLite2 数据库。"),
 group("自定义 GeoIP 数据库 URL",[row("自定义 GeoIP 数据库 URL","textfield","空（占位「自定义 GeoIP 数据库 URL (MaxMind 格式)」）",layer=P,subhub="none",maps_to="[General] geoip-maxmind-url"),row("自动更新","toggle","开",layer=A,subhub="unverified")],"启动该选项后 Surge 将每周自动进行 GeoIP 数据库更新。")],
 ["more-advanced-geoip.png"],[("现在更新…","动作")],note="「最后更新」显示的时间落在本次遍历期间，我没点「现在更新」，应是 App 自己的自动更新"))
S.append(screen("more-advanced-ipv6",ADV+["IPv6"],"IPv6",PUSH,[
 group(None,[row("IPv6 DNS 查询","toggle","关",layer=P,subhub="writes",maps_to=iv("surge_ipv6"),note="推断对应 [General] ipv6")],"启用完整的 IPv6 支持。具体来说，启用此选项后，在访问域名时将查询该域名的AAAA记录。即使未启用此选项，也可以通过直接访问IPv6地址来访问IPv6网站。开启该选项可能会略微增加延迟，如果DNS服务器在查找AAAA记录时出现问题，则可能显著增加延迟。仅在必要时启用。"),
 group(None,[row("IPv6 VIF","popup","禁用 ⌃⌄",layer=P,subhub="none",maps_to="[General] ipv6-vif")],"允许 Surge VIF 处理 IPv6 请求，当需要 Surge 处理直接使用 IPv6 地址的 raw TCP 请求时可开启。\n\n自动：仅在当前网络支持 IPv6，且 IPv6 查询开关打开的状态下开启\n总是：总是开启 IPv6 VIF。\n禁用：完全关闭 IPv6 VIF。")],
 ["more-advanced-ipv6.png"],kind="form"))
S.append(screen("more-advanced-takeover",ADV+["接管模式"],"接管模式",PUSH,[
 group(None,[row("默认","segmented","✓；副标题「标准接管模式，以 TUN 设备对全局网络进行接管。」",layer=A,subhub="unverified"),
  row("代理接管优先","segmented","副标题「在标准接管模式的基础上，同时配置系统代理，以此减少接管请求时产生的额外开销。但是部分应用可能会拒绝在代理模式下工作。」",layer=A,subhub="unverified"),
  row("非默认路由","segmented","副标题「与标准模式类似，但是不配置 TUN 设备为默认路由，使用若干个子路由条目进行接管。以此绕过在标准模式下，HomeKit Camera 无法连接的问题。」",layer=A,subhub="unverified")])],
 ["more-advanced-takeover.png"],kind="picker",note="单选；按简报不切换。存配置还是存本机没核对"))
def T(k,v,f,**kw):
    kw.setdefault('maps_to','[General] '+k)
    return group(k,[row("开启","toggle",v,layer=P,**kw)],f)
def TX(k,v,f,**kw):
    kw.setdefault('maps_to','[General] '+k)
    return group(k,[row(k,"textfield",v,layer=P,**kw)],f)
S.append(screen("more-advanced-advset",ADV+["高级设置"],"高级设置",PUSH,[
 group("路由",[row("包含所有网络请求","toggle","关",layer=P,subhub="none",maps_to="[General] include-all-networks"),row("包含本地网络请求","toggle","关",layer=P,subhub="none",maps_to="[General] include-local-networks"),row("包含 APNS","toggle","关",layer=P,subhub="none",maps_to="[General] include-apns"),row("包含蜂窝服务","toggle","关",layer=P,subhub="none",maps_to="[General] include-cellular-services"),row("包含设备通信","toggle","关",layer=P,subhub="none",note="app-guide：键名未确认")],
  "默认情况下，部分请求可能不会被 Surge 接管。比如应用可以强行绑定物理网卡以绕过 Surge VIF。开启该选项后可以保证所有请求都由 Surge 所接管，没有泄漏，此时可将 Surge 当做防火墙使用。\n如果还想让 Surge 处理所有本地网络的请求，可开启包含本地网络请求选项。\n开启这些选项会引起严重的副作用，如 AirDrop、Xcode Debugger、Surge Dashboard USB 模式等无法正常使用，请仅在需要的特定情况下开启。"),
 T("show-error-page","开","当请求遇到错误时显示 HTTP 错误页面。",subhub="none"),
 T("show-error-page-for-reject","关","如果请求是普通 HTTP 请求，为 REJECT 策略显示错误网页。",subhub="none"),
 T("auto-suspend","开","当发现当前网络由 Surge Gateway 所接管时，自动暂停 Surge iOS。",subhub="none"),
 T("encrypted-dns-follow-outbound-mode","关","默认情况下，加密 DNS 查询使用直连出站。启用此选项会让 DOH 跟随出站模式设置和规则。",subhub="writes",maps_to=iv("surge_encrypted_dns_follow_outbound_mode")),
 T("encrypted-dns-skip-cert-verification","关","跳过加密 DNS 服务器证书验证，这是不安全的。",subhub="none"),
 T("allow-dns-svcb","关（截图只露出一半）","iOS/macOS 系统可能会执行 SVCB 记录 DNS 查询而不是标准的 A 记录查询。这会导致 Surge 无法返回虚拟 IP 地址。因此默认情况下，禁止 SVCB 记录查询以强制系统执行 A 记录查询。",subhub="none"),
 TX("hijack-dns","空（占位「逗号分隔」）","默认情况下，Surge 仅对发送到 Surge DNS 地址（198.18.0.x）的 DNS 查询返回伪造的 IP 地址。发送到标准 DNS 的查询将被转发。\n某些设备或软件总是使用硬编码的 DNS 服务器。（例如，Google 音箱始终使用 8.8.8.8）。您可以使用此选项劫持查询以获取伪造地址。\n您可以使用 hijack-dns = *:53 劫持所有 DNS 查询。",subhub="none"),
 TX("always-real-ip","空（占位「逗号分隔」）","此选项要求 Surge VIF 处理 DNS 查询时返回真实 IP 地址，而不是伪造的 IP 地址。\nDNS 请求包将被转发到上游 DNS 服务器。",subhub="writes",maps_to=iv("surge_always_real_ip")),
 TX("force-http-engine-hosts","空（占位「逗号分隔」）","强制让 Surge 将 TCP 连接视为 HTTP 请求。Surge 的 HTTP 引擎会处理这些请求，以开启高级功能，例如抓包、重写和脚本。\n支持通配符 * 和 ?。\n• 使用前缀 - 排除某个主机名。\n• 默认情况下，仅解密发送到 80 端口的请求。\n• 使用后缀 :port 允许其他端口。\n• 使用后缀 :0 允许所有端口。\n\n示例：\n• -*.apple.com: 排除所有发送到 *.apple.com 的 80 端口请求。\n• www.google.com: 对 www.google.com 的 80 端口强制使用 HTTP 处理。\n• www.google.com:8080: 对 www.google.com 的 8080 端口强制使用 HTTP 处理。\n• www.google.com:0: 对 www.google.com 的所有端口强制使用 HTTP 处理。\n• *:0: 对所有主机名的所有端口强制使用 HTTP 处理。",subhub="none"),
 TX("always-raw-tcp-hosts","空（占位「逗号分隔」）","Surge 会自动对发往 80 与 443 端口的 TCP 请求进行协议嗅探，以开启 HTTP/HTTPS 相关的高级功能，同时优化性能，但这可能会导致一些兼容性问题。如果你遇到了问题，可以将主机名添加到此处，Surge 将不会对这些请求进行协议嗅探。",subhub="none"),
 TX("always-raw-tcp-keywords","空（占位「逗号分隔」）","在进行协议嗅探时，如果 HTTP Header 中出现特定关键词，则将该请求回退到原始 TCP 处理，这可以用来避免一些兼容性问题。",subhub="none"),
 TX("tun-excluded-routes","空（占位「逗号分隔」）","Surge VIF 只能处理 TCP 和 UDP 协议。使用此选项绕过特定的 IP 范围以允许所有流量通过。\n注意：此选项仅适用于 Surge VIF。由 Surge 代理服务器处理的请求不受影响。结合 'skip-proxy' 和 'tun-excluded-routes' 确保特定的 HTTP 流量绕过 Surge。",subhub="writes",maps_to=iv("surge_tun_excluded_routes")),
 TX("tun-included-routes","空（占位「逗号分隔」）","默认情况下，Surge VIF 接口将自己声明为默认路由。但是，由于 Wi-Fi 接口有更小的路由，一些流量可能不会通过 Surge VIF 接口。使用此选项添加更小的路由。",subhub="none"),
 TX("skip-proxy","空（占位「空」）","注意：此选项的目的并不是阻止请求通过代理发出。\n在 iOS 版本中，此选项会强制将连接这些域名/IP 段的流量交由 Surge VIF 处理，而不是 Surge 代理。在 macOS 版本中，当启用 \"设置为系统代理\" 时，这些设置将应用到系统。该选项用于解决某些应用的兼容性问题。\n • 如需指定单一域名，请直接输入域名，例如 apple.com.\n • 如需指定整个域名下的所有网站，请在域名前加星号，例如 *apple.com.\n • 如需指定域名的特定子部分，请逐级指定，例如 store.apple.com.\n • 如需按 IP 地址指定主机或网络，请输入单个 IP（如 192.168.2.11）或一个地址范围，例如 192.168.2.* 或 192.168.2.0/24.\n注意：如果输入的是 IP 地址或地址范围，只有在使用该地址连接主机时才能绕过代理，而当通过解析到该地址的域名连接时则无法绕过代理。",subhub="writes",maps_to=iv("surge_skip_proxy")),
 T("exclude-simple-hostnames","开","就像 skip-proxy 参数一样。此选项让使用简单主机名（不带点）的请求由 Surge VIF 而不是 Surge 代理处理。",subhub="none"),
 TX("proxy-test-udp","空（占位「空」）","代理的默认 UDP 测试参数。例如：apple.com@1.0.0.1",subhub="none"),
 TX("wifi-access-http-auth","空（占位「空」）","Require authentication for Surge HTTP proxy service.\nE.g.: username:password",subhub="none",note="有值时属敏感值"),
 T("proxy-restricted-to-lan","开","Restrict proxy or gateway services to only accept devices from the current subnet. Enabled by default.",subhub="none"),
 T("icmp-forwarding","开","允许 Surge 转发 ICMP ping 数据包，关闭后 ping 将无法使用。",subhub="none")],
 ["more-advanced-advset-warning.png"]+[f"more-advanced-advset_{i}.png" for i in range(1,8)],kind="form",
 note="进入时先弹「警告」：调整这里的任何一项设置均有可能引发各种问题。请先阅读各项设置的说明，明确理解该设置的意义后再进行调整。按钮只有「好的」，点了它。页面形态：分组 header 用键名原文（等宽小写），组内只有一行「开启」开关或一个输入框。当前配置 sg3-b 中 always-real-ip / tun-excluded-routes / skip-proxy 都为空（它不是 SubHub 生成的配置）"))

# ---------- 工具 tab ----------
NA="未启动时不可用（行灰显）"
S.append(screen("tools",["工具 tab"],"工具",{},[
 group("当前状态",[row(n,"disclosure",NA,layer=A,subhub="na") for n in ["最近请求","DNS 结果","实时统计","网络诊断","事件","实时浮窗","临时规则","终端"]]),
 group("已保存数据",[row(n,"disclosure",None,layer=A,subhub="na") for n in ["已保存的捕获数据","已保存的数据包捕获会话","流量统计","日志簿","Wi-Fi 时间轴"]]),
 group("远端控制器",[row("远端控制器","disclosure",None,layer=A,subhub="none"),row("云通知","disclosure",None,layer=A,subhub="none")]),
 group("工具",[row("iPerf 测试","disclosure",None,layer=X,subhub="na"),row("脚本编辑器","disclosure",None,layer=X,subhub="na")]),
 group(None,[row("路由表","disclosure",None,layer=A,subhub="na"),row("日志","disclosure",None,layer=A,subhub="na")])],
 ["tools.png","tools_2.png"],[("当前状态 8 项",NA),("已保存数据 / 路由表 / 日志","数据查看页，可能含访问记录，不进"),("远端控制器 / 云通知 / iPerf / 脚本编辑器","工具与动作页，不进")],kind="list",
 note="大标题样式；每行左侧有圆角彩色图标"))

# ---------- 更多 tab ----------
M=["更多 tab"]
S.append(screen("more",M,"更多",{},[
 group("授权",[row("授权管理","disclosure",layer=A,subhub="na"),row("已解锁的功能","disclosure",layer=A,subhub="na")]),
 group("主题",[row("Gradient / Lucid","theme-picker","Lucid（蓝框选中）",layer=A,subhub="device",note="两张主题卡片；按简报不切换")]),
 group("外观",[row(n,"disclosure",layer=A,subhub="device") for n in ["深色外观","收藏的卡片","应用图标","快捷动作","开始标签页"]]),
 group("其他平台",[row("Surge Mac","disclosure",layer=A,subhub="na"),row("Surge tvOS","disclosure",layer=A,subhub="na")]),
 group("设置",[row("配置升级","disclosure",None,"more-profile-upgrade",layer=X,subhub="unverified"),row("始终开启","disclosure",None,"more-always-on",layer=A,subhub="device"),row("警告信息","disclosure",layer=A,subhub="device"),row("通知","disclosure",layer=A,subhub="device"),row("配置同步","disclosure",None,"more-profile-sync",layer=A,subhub="device"),row("密钥库","disclosure",layer=A,subhub="device"),row("动态资源","disclosure",layer=A,subhub="device"),row("分析与提升","disclosure",layer=A,subhub="device")]),
 group("帮助",[row(n,"disclosure",layer=X,subhub="na") for n in ["手册","配置参数表","理解 Surge","常见问题"]]),
 group("关于",[row(n,"disclosure",layer=X,subhub="na") for n in ["在 App Store 中评价 Surge","致谢","使用条款","隐私策略"]],"Version 5.23.0 (Build 3867, SDK 27.1)")],
 ["more.png","more_2.png","more_3.png","more_4.png"],
 [("授权管理 / 已解锁的功能","含账户与授权信息，不进"),("密钥库","可能含密钥，不进"),("外观各项 / 警告信息 / 通知 / 动态资源 / 分析与提升","本机设置，时间优先未进"),("帮助 / 关于","外链或文档")],kind="list"))
S.append(screen("more-profile-upgrade",M+["配置升级"],"新功能",{"right":"取消"},[
 group(None,[row("Smart 策略组","card","已包含在更新订阅中",layer=P,subhub="unverified",note="卡片正文：一种全新的策略组类型，由我们精心设计的算法引擎所驱动，可以自动从该策略组的子策略中选择合适的策略。执行此项更新会自动把所有自动测试类型策略组（url-test/load-balance）升级为智能策略组。"),
  row("了解更多 ›","link",layer=X,subhub="na"),row("应用该更新","toggle","开",layer=P,subhub="unverified")],"Surge 在最新的更新中包含了一些新功能，该向导可以自动调整你的配置以获得最佳体验。自动调整对托管配置亦可生效。"),
 group(None,[row("确认","button",layer=X,subhub="na",note="未点")],"请注意，执行配置升级后，所有使用该配置的 Surge 均需要升级到最新版本。Surge Mac 需升级到 v5.7.0 以上。")],
 ["more-profile-upgrade.png"],[("确认","会改写配置")],kind="wizard",
 note="全屏向导，用「取消」退出。对 SubHub 重要：它会把 SubHub 写的 url-test 组改成 smart，并说对托管配置也生效"))
S.append(screen("more-always-on",M+["始终开启"],"始终开启",PUSH,[group(None,[row("自动启动 Surge","toggle","关",layer=A,subhub="device")],"启动该选项后 Surge 将保持运行，即使在系统重启后也能自动开启。")],["more-always-on.png"]))
S.append(screen("more-profile-sync",M+["配置同步"],"配置同步",PUSH,[group(None,[row("无","segmented","✓",layer=A,subhub="device"),row("iCloud 云盘","segmented",layer=A,subhub="device"),row("Dropbox","segmented",layer=A,subhub="device")])],["more-profile-sync.png"],kind="picker"))

dump("surge",{"version":"5.23.0 (Build 3867, SDK 27.1)","captured":"2026-11-11","device":"iPhone 17 Pro（镜像窗口）","current_profile":"sg3-b（实验配置，非 SubHub 生成）","vpn_state":"未启动（未改动）","tabs":["首页（通用/捕获/修改）","工具","更多"],
 "legend":{"layer":{"profile":"写进配置","app":"只在本机","action":"动作"},"subhub":REL}},S)
