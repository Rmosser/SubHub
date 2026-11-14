from common import *
P="profile";A="app";X="action"
iv=lambda k:f"intent {k}"
S=[]
PUSH={"left":"返回"}
SHEET={"left":"✕"}
PC=["首页 tab","配置名 ⌄（配置中心）"]
PD=PC+["当前配置 ⓘ"]

# ---------- 首页 ----------
S.append(screen("home",["首页 tab"],"<lan-host>(3)（首页）",{"left":"配置名 ⌄","right":"启动"},[
 group(None,[row("连接状态","readonly","未连接",layer=A,subhub="na")]),
 group("出站模式（卡片）",[row("全局","segmented",None,layer=P,subhub="unverified",maps_to="mode",note="单选；按简报不切换"),row("规则","segmented","✓；副标题「按配置的规则转发流量」",layer=P,subhub="unverified",maps_to="mode"),row("直连","segmented",None,layer=P,subhub="unverified",maps_to="mode")]),
 group("代理（卡片）",[row("代理","disclosure","3 个代理","home-proxies",layer=P,subhub="writes",maps_to="proxies / proxy-groups")]),
 group("规则（卡片）",[row("规则","disclosure","2 条规则；副标题「ss-a 1」","home-rules",layer=P,subhub="writes",maps_to="rules")]),
 group("流量（卡片）",[row("上传 / 下载","readonly","0 Kbps；0 B 累计",layer=A,subhub="na")])],
 ["home.png"],[("启动","会启动 VPN"),("流量卡片下方","未滚动查看")],kind="home",note="卡片式首页，与 Surge 首页同一套布局"))
S.append(screen("home-proxies",["首页 tab","代理"],"代理",{"left":"✕","right":"⚡ 测速 / 折叠 / ⟳ / 筛选"},[
 group("未入组（副标题「未被任何分组引用」，右侧数量 3 与折叠箭头）",[row("<节点名>","row","副标题协议「SS」；右侧 ⚡ 与 ⓘ",None,layer=P,subhub="writes",maps_to="proxies",note="点行在有组时会切换节点；只记一条结构"),row("节点 ⓘ","disclosure",None,"home-node-edit",layer=P,subhub="writes",maps_to="proxies")]),
 group(None,[row("搜索代理","searchfield",layer=A,subhub="na")])],
 ["home-proxies.png"],[("⚡ / ⟳ / 筛选","测速与动作")],kind="list",note="当前配置没有 proxy-groups，所以只有「未入组」"))
S.append(screen("home-node-edit",["首页 tab","代理","节点 ⓘ"],"编辑节点",{"left":"✕","right":"保存（灰，未改动时不可点）"},[
 group("身份",[row("代理类型","popup","Shadowsocks ⌃⌄",layer=P,subhub="writes",maps_to="proxies[].type"),row("名称","textfield","<节点名>",layer=P,subhub="writes",maps_to="proxies[].name")]),
 group("已配置的选项",[row("服务器地址","textfield","<redacted>",layer=P,subhub="writes",maps_to="proxies[].server"),row("端口","textfield","<redacted>",layer=P,subhub="writes",maps_to="proxies[].port"),row("密码","textfield","<redacted>（掩码，眼睛图标）",layer=P,subhub="writes",maps_to="proxies[].password"),row("加密方式","popup","<redacted>",layer=P,subhub="writes",maps_to="proxies[].cipher"),
  row("插件","popup","未设置 ⌃⌄",layer=P,subhub="unverified",maps_to="proxies[].plugin"),row("插件设置","disclosure","未设置",layer=P,subhub="unverified",maps_to="proxies[].plugin-opts"),
  row("TCP 快速打开","toggle","关",layer=P,subhub="unverified",maps_to="proxies[].tfo"),row("UDP 转发","toggle","开",layer=P,subhub="writes",maps_to="proxies[].udp（intent clash_udp_default_enabled）"),row("UDP 走 TCP","toggle","关",layer=P,subhub="unverified",maps_to="proxies[].udp-over-tcp")]),
 group(None,[row("更多字段","disclosure",layer=P,subhub="unverified")])],
 ["home-node-edit_1.png","home-node-edit_2.png"],[("更多字段 / 插件设置","子页未进")],kind="form",note="分组名「已配置的选项」暗示只列出配置里写了的字段；地址、端口、密码、加密方式在截图里已涂黑"))
S.append(screen("home-rules",["首页 tab","规则"],"规则",{"left":"✕","right":"编辑"},[
 group("规则（2）",[row("<目标策略>","disclosure","右侧条数 1",layer=P,subhub="writes",maps_to="rules")],"按目标分组。这是正在生效的规则：配置里的规则，加上你的自定义规则和覆写脚本"),
 group("Fallback",[row("MATCH","readonly","徽标 <策略名>",layer=P,subhub="writes",maps_to="rules MATCH")],"以上都未命中的流量。"),
 group(None,[row("运行中的规则","disclosure","灰；副标题「连接 Clash 后可查看正在生效的规则」",layer=A,subhub="na",note="未启动时不可用")]),
 group(None,[row("搜索规则","searchfield",layer=A,subhub="na")])],
 ["home-rules.png"],[("编辑","进编辑模式"),("规则分组行","子列表，未进"),("运行中的规则","未启动时不可用")],kind="list"))

# ---------- 配置中心 ----------
S.append(screen("profiles",PC,"配置中心",{"left":"✕","right":"排序 / +"},[
 group(None,[row("配置库 / 节点库 / 规则库","segmented","配置库",layer=A,subhub="na")]),
 group("配置（右侧数量 4）",[row("<配置名>","row","左侧 ✓ = 使用中；副标题「N 个节点」；徽标「原始配置」；右侧 ⓘ",None,layer=A,subhub="device",note="点行即切换当前配置，未点"),row("当前配置 ⓘ","disclosure",None,"profile-detail",layer=P,subhub="writes")]),
 group(None,[row("全部更新","action",layer=X,subhub="na")]),
 group("添加配置",[row("https://example.com/config.yaml","textfield","占位；右侧粘贴按钮",layer=X,subhub="na",note="SubHub 订阅链接从这里导入"),row("扫描二维码","action",layer=X,subhub="na"),row("导入文件","action",layer=X,subhub="na")]),
 group(None,[row("模块","disclosure","关闭",layer=A,subhub="unverified")])],
 ["profiles.png"],[("配置行","点即切换配置"),("节点库 / 规则库","分段切换，未看"),("全部更新 / 添加配置","动作"),("模块","未进")],kind="list"))
S.append(screen("profile-detail",PD,"<配置名>",SHEET,[
 group("配置管理（右侧「✓ 使用中」）",[row("名称","textfield","<配置名>",layer=A,subhub="device"),row("随链接更新","toggle","开",layer=A,subhub="device"),row("立即同步","action","前天",layer=X,subhub="na"),row("链接设置","action",layer=A,subhub="device",note="内含订阅链接，未进")]),
 group("配置覆写",[row("规则方案","popup","原始配置 ⌃⌄",layer=A,subhub="device"),row("自定义规则","disclosure",layer=A,subhub="device"),row("覆写脚本","disclosure",layer=A,subhub="device")],"原始配置只用它自己的规则，规则库的改动不会生效；要用规则库，请在上方选一个规则方案。\n自定义规则和覆写脚本只属于这份配置，换方案时不变。"),
 group("<配置名> 配置详情",[
  row("全局配置","disclosure",None,"profile-global",layer=P,subhub="partial",maps_to="顶层 mode / log-level / ipv6 / external-controller …"),
  row("DNS","disclosure",None,"profile-dns",layer=P,subhub="writes",maps_to="dns"),
  row("域名嗅探","disclosure",None,layer=P,subhub="writes",maps_to="sniffer（intent clash_sniffer_*）"),
  row("入站","disclosure",None,"profile-inbound",layer=P,subhub="partial",maps_to="tun / mixed-port / allow-lan"),
  row("出站代理","disclosure","3",layer=P,subhub="writes",maps_to="proxies"),row("代理集合","disclosure",layer=P,subhub="unverified",maps_to="proxy-providers"),row("代理组","disclosure",layer=P,subhub="writes",maps_to="proxy-groups"),
  row("路由规则","disclosure","2",layer=P,subhub="writes",maps_to="rules"),row("规则集合","disclosure",layer=P,subhub="writes",maps_to="rule-providers"),row("子规则","disclosure",layer=P,subhub="unverified",maps_to="sub-rules"),
  row("流量隧道","disclosure",layer=P,subhub="none",maps_to="tunnels"),row("NTP","disclosure",layer=P,subhub="none",maps_to="ntp"),row("实验性配置","disclosure",layer=P,subhub="none",maps_to="experimental")]),
 group(None,[row("编辑源码","action",layer=X,subhub="na"),row("检查配置","action",layer=X,subhub="na"),row("存成规则方案","action",layer=X,subhub="na"),row("复制配置","action",layer=X,subhub="na"),row("导出","action",layer=X,subhub="na")],"改动即时生效；「检查配置」只做检查，不会应用"),
 group(None,[row("查看生效中的配置","action",layer=X,subhub="na")],"只读"),
 group(None,[row("删除配置","button",layer=X,subhub="na",note="红色；使用中的配置为灰色")]),
 group(None,[row("搜索","searchfield",layer=A,subhub="na")])],
 ["profile-detail_1.png","profile-detail_2.png","profile-detail_3.png"],
 [("链接设置","含订阅链接"),("域名嗅探 / 出站代理 / 代理集合 / 代理组 / 路由规则 / 规则集合 / 子规则 / 流量隧道 / NTP / 实验性配置","时间优先，只进了全局配置、DNS、入站"),("编辑源码 / 查看生效中的配置","整份配置原文，含节点敏感值"),("检查 / 存成方案 / 复制 / 导出 / 删除","动作")],
 note="这一层就是简报要的「核心设置」：配置详情下的每一项对应 Mihomo YAML 的一个顶层段。脚注说「改动即时生效」，所以没有保存按钮"))
S.append(screen("profile-global",PD+["全局配置"],"全局配置",PUSH,[
 group("出站",[row("运行模式","popup","规则分流 ⌃⌄",layer=P,subhub="unverified",maps_to="mode")]),
 group("日志",[row("日志级别","popup","信息 ⌃⌄",layer=P,subhub="writes",maps_to=iv("clash_log_level"))]),
 group("连接",[row("IPv6","toggle","关",layer=P,subhub="writes",maps_to=iv("clash_ipv6")),row("统一延迟","toggle","开",layer=P,subhub="none",maps_to="unified-delay"),row("TCP 并发连接","toggle","关",layer=P,subhub="writes",maps_to=iv("clash_tcp_concurrent")),row("关闭 TCP 保活","toggle","关",layer=P,subhub="none",maps_to="disable-keep-alive"),row("TCP 保活空闲时间","popup","默认 · 5 分钟",layer=P,subhub="none",maps_to="keep-alive-idle"),row("TCP 保活间隔","popup","默认 · 75 秒",layer=P,subhub="none",maps_to="keep-alive-interval"),row("GeoSite 匹配方式","popup","默认（紧凑）",layer=P,subhub="none",maps_to="geosite-matcher")]),
 group("其余字段",[row("控制接口","popup","关闭 ⌃⌄",layer=P,subhub="writes",maps_to=iv("clash_external_controller")),row("控制接口套接字","disclosure","关闭",layer=P,subhub="none",maps_to="external-controller-unix"),row("控制接口（HTTPS）","popup","关闭 ⌃⌄",layer=P,subhub="none",maps_to="external-controller-tls"),
  row("面板文件夹","disclosure","无",layer=P,subhub="writes",maps_to=iv("clash_external_ui")),row("面板下载地址","disclosure","默认 · MetaCubeXD",layer=P,subhub="writes",maps_to=iv("clash_external_ui_url")),row("面板子文件夹","disclosure","直接放在面板文件夹",layer=P,subhub="writes",maps_to=iv("clash_external_ui_name")),
  row("控制接口上的 DoH","disclosure","关闭",layer=P,subhub="none",maps_to="external-doh-server"),row("访问密钥","disclosure","无",layer=P,subhub="writes",maps_to=iv("clash_secret"),note="有值时属敏感值；当前为「无」"),
  row("dat 版 GeoIP","toggle","关",layer=P,subhub="none",maps_to="geodata-mode"),row("全局 TLS 指纹","disclosure","无",layer=P,subhub="none",maps_to="global-client-fingerprint"),row("下载时的 UA","disclosure","clash.meta",layer=P,subhub="none",maps_to="global-ua"),row("ETag 缓存","toggle","开",layer=P,subhub="none",maps_to="etag-support"),
  row("多网络策略","popup","默认（只用当前网络）",layer=P,subhub="none"),row("优先使用的网络","disclosure","按策略决定",layer=P,subhub="none"),row("备用网络","disclosure","其他所有网络",layer=P,subhub="none"),row("TLS 证书","disclosure","未设置；副标题「在『证书与信任』里改」",layer=P,subhub="none")]),
 group("控制接口跨域",[row("允许的网页来源","disclosure","全部",layer=P,subhub="none",maps_to="external-controller-cors.allow-origins"),row("允许私有网络访问","toggle","开",layer=P,subhub="none",maps_to="external-controller-cors.allow-private-network")],"哪些网页可以在浏览器里调用控制接口。"),
 group("重启后保留",[row("记住节点选择","toggle","开",layer=P,subhub="writes",maps_to=iv("clash_profile_store_selected")),row("保存虚拟 IP 映射","toggle","开",layer=P,subhub="writes",maps_to=iv("clash_profile_store_fake_ip"))],"内核重启后不用重新选节点，连接也不会因虚拟 IP 改变而断开。"),
 group("规则数据库下载地址",[row(n,"disclosure","默认 · 官方（GitHub）",layer=P,subhub="none",maps_to="geox-url."+k) for n,k in [("GeoIP","geoip"),("MMDB","mmdb"),("ASN","asn"),("GeoSite","geosite")]],"一般不用改；访问 GitHub 困难时换成镜像。"),
 group(None,[row("9 项在 iPhone 上不起作用","disclosure",None,"profile-global-ios-noop",layer=P,subhub="na")])],
 ["profile-global_1.png","profile-global_2.png","profile-global_3.png","profile-global_4.png"],[("各弹出菜单与子页","避免误改；值已从行尾读出")],kind="form",
 note="中文行名与 YAML 键的对应是我按 Mihomo 文档推断的（maps_to 里未写 intent 的都属推断）；allow-lan / mixed-port 不在这一页，见「入站」"))
S[-1]["floating"]=[row("搜索","searchfield",layer=A,subhub="na",note="底部悬浮玻璃搜索框，按行名筛选本页")]
S.append(screen("profile-global-ios-noop",PD+["全局配置","9 项在 iPhone 上不起作用"],"不起作用的设置",PUSH,[
 group(None,[row("进程匹配","readonly","由 Clash 自己设定；这里固定关闭：系统不告诉 App 连接来自哪个应用，按进程匹配的规则不会命中。",layer=P,subhub="na",maps_to="find-process-mode"),
  row("控制接口路由标记","readonly","iPhone 上没有这项功能；路由标记是 Linux 的功能，这里不会给控制接口的流量打标记。",layer=P,subhub="na"),
  row("控制接口命名管道","readonly","iPhone 上没有这项功能；命名管道是 Windows 的功能，这里不会打开。",layer=P,subhub="na",maps_to="external-controller-pipe"),
  row("出站网卡","readonly","这里用不到，已略过；这里会被去掉：出站用哪块网卡由隧道自己决定。",layer=P,subhub="na",maps_to="interface-name"),
  row("路由标记","readonly","iPhone 上没有这项功能；路由标记是 Linux 的功能，这里出站流量不会打标记。",layer=P,subhub="na",maps_to="routing-mark"),
  row("自动更新 GEO 数据","readonly","由 Clash 自己设定；这里固定关闭：GEO 数据库由 App 下载好再交给 Clash。",layer=P,subhub="na",maps_to="geo-auto-update"),
  row("GEO 更新间隔","readonly","iPhone 上没有这项功能；不起作用：这里 Clash 不会自己定时更新 GEO 数据库。",layer=P,subhub="na",maps_to="geo-update-interval"),
  row("GEO 加载方式","readonly","由 Clash 自己设定；这里固定用省内存方式，数据按需读取，不整份放进内存。",layer=P,subhub="na",maps_to="geodata-loader"),
  row("Clash 安卓版专用","readonly","iPhone 上没有这项功能；这组只有 Clash for Android 读取，在这里不起作用。",layer=P,subhub="na")],
  "在 iPhone 上，这些由 Clash 自己处理，写在这里的值不会用到。")],
 ["profile-global-ios-noop.png"],kind="list",note="每行三层文字：名称 / 状态 / 说明。这页对「SubHub 写了但 iPhone 不用」的提示很有参考价值"))
S.append(screen("profile-dns",PD+["DNS"],"DNS",PUSH,[
 group("基本",[row("DNS 模式","popup","虚拟 IP (fake-ip) ⌃⌄",layer=P,subhub="writes",maps_to=iv("clash_dns_enhanced_mode")),row("解析 IPv6","toggle","关",layer=P,subhub="unverified",maps_to="dns.ipv6"),row("使用 Hosts 映射","toggle","开",layer=P,subhub="writes",maps_to=iv("clash_dns_use_hosts")),row("使用系统 Hosts","toggle","开",layer=P,subhub="none",maps_to="dns.use-system-hosts"),row("DNS 遵循路由规则","toggle","关",layer=P,subhub="writes",maps_to=iv("clash_dns_respect_rules"))],"是否由 Clash 负责解析域名，以及用哪种模式。"),
 group("上游服务器",[row("引导 DNS","disclosure","1 项",layer=P,subhub="writes",maps_to=iv("clash_dns_default_nameserver")),row("DNS 服务器","disclosure","1 项",layer=P,subhub="writes",maps_to=iv("clash_dns_nameserver")),row("备用 DNS 服务器","disclosure","无",layer=P,subhub="writes",maps_to=iv("clash_dns_fallback")),row("节点域名 DNS","disclosure","1 项",layer=P,subhub="writes",maps_to=iv("clash_dns_proxy_server_nameserver")),row("直连 DNS","disclosure","1 项",layer=P,subhub="writes",maps_to=iv("clash_dns_direct_nameserver")),row("直连 DNS 按分域名","toggle","关",layer=P,subhub="none",maps_to="dns.direct-nameserver-follow-policy"),row("优先 HTTP/3","toggle","关",layer=P,subhub="none",maps_to="dns.prefer-h3")],"引导 DNS 只能填 IP，用来解析其他服务器的域名。"),
 group("按域名分流",[row("分域名 DNS","disclosure","无",layer=P,subhub="writes",maps_to=iv("clash_dns_nameserver_policy")),row("分域名节点 DNS","disclosure","无",layer=P,subhub="none",maps_to="dns.proxy-server-nameserver-policy")],"让特定域名交给指定的服务器解析。"),
 group("备用规则",[row("按需查询备用","toggle","关",layer=P,subhub="none")],"什么情况下改用备用服务器的解析结果。"),
 group("虚拟 IP",[row("IPv4 网段","disclosure","198.19.0.1/16",layer=P,subhub="writes",maps_to=iv("clash_dns_fake_ip_range")),row("IPv6 网段","disclosure","无",layer=P,subhub="none",maps_to="dns.fake-ip-range6"),row("不用虚拟 IP 的域名","disclosure","内置少量域名",layer=P,subhub="writes",maps_to=iv("clash_fake_ip_filter")),row("过滤模式","popup","默认（列表内用真实 IP）",layer=P,subhub="writes",maps_to=iv("clash_dns_fake_ip_filter_mode")),row("有效期","popup","默认 · 1 秒",layer=P,subhub="none",maps_to="dns.fake-ip-ttl")],"只在 DNS 模式为虚拟 IP 时生效；一般不用改。"),
 group("更多设置",[row("IPv6 等待时间","popup","默认 · 100 毫秒",layer=P,subhub="none"),row("DNS 缓存算法","popup","默认（最近最少使用）",layer=P,subhub="none",maps_to="dns.cache-algorithm"),row("DNS 缓存条数","disclosure","默认 · 1024",layer=P,subhub="none")]),
 group("备用 DNS 条件",[row("按 GeoIP 判断","toggle","开",layer=P,subhub="none",maps_to="dns.fallback-filter.geoip"),row("信任的国家","disclosure","默认 · 中国大陆",layer=P,subhub="none",maps_to="dns.fallback-filter.geoip-code"),row("可疑的 IP 段","disclosure","无",layer=P,subhub="none",maps_to="dns.fallback-filter.ipcidr"),row("只用备用的域名","disclosure","无",layer=P,subhub="none",maps_to="dns.fallback-filter.domain"),row("只用备用的分类","disclosure","无",layer=P,subhub="none",maps_to="dns.fallback-filter.geosite")],"什么情况下改用备用服务器的结果。"),
 group(None,[row("本地域名映射","disclosure","无",layer=P,subhub="writes",maps_to=iv("clash_host_records")+"（hosts）")]),
 group(None,[row("2 项在 iPhone 上不起作用","disclosure",layer=P,subhub="na",note="未进")])],
 ["profile-dns_1.png","profile-dns_2.png","profile-dns_3.png","profile-dns_4.png"],[("各列表子页","值是服务器地址，只记条数"),("2 项在 iPhone 上不起作用","时间优先未进")],kind="form",
 note="intent clash_dns_enable / clash_dns_listen 在这页没有对应行（可能在「2 项不起作用」里）"))
S.append(screen("profile-inbound",PD+["入站"],"入站",PUSH,[
 group(None,[row("局域网代理共享","disclosure","关闭",layer=P,subhub="writes",maps_to=iv("clash_allow_lan")+" / "+iv("clash_mixed_port"),note="推断：allow-lan 与端口在这个子页")]),
 group(None,[row("SS 入站链接","disclosure","关闭",layer=P,subhub="none",maps_to="ss-config"),row("VMess 入站链接","disclosure","关闭",layer=P,subhub="none",maps_to="vmess-config"),row("入站 TCP 快速打开","toggle","关",layer=P,subhub="none",maps_to="inbound-tfo"),row("入站多路径 TCP","toggle","关",layer=P,subhub="none",maps_to="inbound-mptcp")]),
 group("DNS 劫持",[row("劫持的地址","disclosure","所有 DNS 查询",layer=P,subhub="writes",maps_to=iv("clash_tun_dns_hijack"))],"把发往这些地址的 DNS 查询交给 Clash 处理。"),
 group("路由",[row("严格路由","disclosure","默认 · 关闭；副标题「在『VPN 与路由』里改」",layer=P,subhub="writes",maps_to=iv("clash_tun_strict_route")),row("只接管的网段","disclosure","全部流量；同上副标题",layer=P,subhub="writes",maps_to=iv("clash_tun_include_routes")),row("只接管的规则集","disclosure","无；同上副标题",layer=P,subhub="none",maps_to="tun.route-address-set"),row("不接管的网段","disclosure","无；同上副标题",layer=P,subhub="writes",maps_to=iv("tun_excluded_routes")),row("不接管的规则集","disclosure","无；同上副标题",layer=P,subhub="none",maps_to="tun.route-exclude-address-set"),
  row("旧版 IPv4 接管网段","disclosure","无",layer=P,subhub="none",maps_to="tun.inet4-route-address"),row("旧版 IPv6 接管网段","disclosure","无",layer=P,subhub="none",maps_to="tun.inet6-route-address"),row("旧版 IPv4 排除网段","disclosure","无",layer=P,subhub="none",maps_to="tun.inet4-route-exclude-address"),row("旧版 IPv6 排除网段","disclosure","无",layer=P,subhub="none",maps_to="tun.inet6-route-exclude-address"),row("回环地址","disclosure","无；同上副标题",layer=P,subhub="none",maps_to="tun.loopback-address")],"哪些目标地址走虚拟网卡，哪些绕开。"),
 group("更多设置",[row("TUN IPv6 地址（推断）","disclosure","fdfe:dcba:9876::1/126；副标题「在『VPN 与路由』里改」",layer=P,subhub="none",note="只露出半行")])],
 ["profile-inbound_1.png","profile-inbound_2.png"],[("「更多设置」后半段","时间优先未滚到底"),("各子页","未进")],kind="form",
 note="「在『VPN 与路由』里改」指向的入口我没找到（更多 tab 只有「VPN」）；tun.enable / stack / auto-route 的对应行没看到"))

# ---------- 工具 ----------
S.append(screen("tools",["工具 tab"],"工具",{},[
 group("本次连接",[row("活动","disclosure","副标题「实时连接、请求与日志」",layer=A,subhub="na")]),
 group("网络工具",[row("网络质量","disclosure","上行、下行与响应度",layer=X,subhub="na"),row("STUN 与 NAT","disclosure","UDP 可达性与 NAT 行为",layer=X,subhub="na"),row("DNS 查询","disclosure","查询域名，清除 DNS 缓存",layer=X,subhub="na"),row("局域网代理共享","disclosure","局域网 HTTP 与 SOCKS 代理",layer=P,subhub="writes",maps_to=iv("clash_allow_lan"))]),
 group("运行状况与报告",[row("运行状况","disclosure","路由、内存压力与运行状况",layer=A,subhub="na"),row("外部资源","disclosure","此配置的代理来源与规则集的运行状态",layer=A,subhub="na"),row("诊断收件箱","disclosure","崩溃、卡顿、CPU、磁盘与能耗报告",layer=A,subhub="na")])],
 ["tools.png"],[("全部入口","活动/运行状况需要连接；其余是测试动作或报告，可能含访问记录")],kind="list",note="每行带彩色圆角图标和灰色副标题，和更多 tab 同一种行"))

# ---------- 更多 ----------
M=["更多 tab"]
S.append(screen("more",M,"更多",{},[
 group("连接行为",[row("按需求连接","disclosure","副标题「Wi-Fi 与蜂窝网络规则」","more-on-demand",layer=A,subhub="device"),row("VPN","disclosure","副标题「强制路由与包括所有网络」","more-vpn",layer=A,subhub="device")]),
 group("应用设置",[row("客户端设置","disclosure","副标题「流量、更新、延迟测试与节点切换」","more-client",layer=A,subhub="device"),row("外观","disclosure","副标题「语言、主题、强调色与深色外观」","more-appearance",layer=A,subhub="device")]),
 group("数据与资源",[row("Geo 资源","disclosure","副标题「GeoIP、GeoSite、ASN 与 MMDB 数据」","more-geo",layer=A,subhub="device"),row("存储空间","disclosure","副标题「配置、数据与缓存」","more-storage",layer=A,subhub="na")]),
 group("关于",[row("关于 Clash","disclosure","副标题「版本、开源与发行信息」","more-about",layer=A,subhub="na")])],["more.png"],kind="list"))
S.append(screen("more-on-demand",M+["按需求连接"],"按需求连接",{"left":"返回","right":"编辑 / +"},[
 group("始终开启",[row("始终开启","toggle","关",layer=A,subhub="device")],"如果是，VPN 连接将始终开启，默认值是否。"),
 group("按需求连接",[row("按需求连接","toggle","关",layer=A,subhub="device")],"开启按需切换 VPN。"),
 group("其他",[row("睡眠时断开","toggle","关",layer=A,subhub="device"),row("显示断开信息","toggle","关",layer=A,subhub="device")],"如果是，VPN 连接将在设备进入睡眠状态时断开。默认值是否"),
 group("按需求规则（header 右侧 +）",[row("Connect","disclosure","Any",layer=A,subhub="device")])],
 ["more-on-demand.png"],[("Connect 规则 / 编辑 / +","表单"),],note="iOS NEOnDemandRule 的包装"))
S.append(screen("more-vpn",M+["VPN"],"VPN",PUSH,[
 group(None,[row("强制路由","toggle","关",layer=A,subhub="device",note="App 说明里提到 tun.strict-route，但这个开关是 iOS VPN 参数")],"开启后，Clash 的路由优先于这台设备上已有的路由。默认关闭"),
 group("包括所有网络",[row("包括所有网络","toggle","关",layer=A,subhub="device")],"开启后，除少数例外，所有流量都经过 Clash\n开启后，更新 Clash 时可能整机断网，要重启设备才能恢复；更新前先关掉"),
 group("包括本地网络",[row("包括本地网络","toggle","关（灰）",layer=A,subhub="device")],"开启后，发往局域网的流量也经过 Clash"),
 group("包括 APNs",[row("包括 APNs","toggle","关（灰）",layer=A,subhub="device")],"开启后，Apple 推送通知的流量也经过 Clash"),
 group("包括蜂窝服务",[row("包括蜂窝服务","toggle","关（灰）",layer=A,subhub="device")],"开启后，蜂窝服务（VoLTE、Wi-Fi 通话、IMS、彩信、可视语音信箱等）的联网流量也经过 Clash"),
 group("隐藏 VPN 图标",[row("隐藏 VPN 图标","toggle","关",layer=A,subhub="device")],"开启后，状态栏不显示 VPN 标记。下次连接时生效"),
 group("HomeKit 兼容",[row("HomeKit 兼容","toggle","关",layer=A,subhub="device")],"开启后，局域网里的 HomeKit 配件保持可用；开启期间「互联网共享」不可用。下次连接时生效\n只在 HomeKit 配件无响应时打开。配置里已设 tun.strict-route 时不必开。"),
 group("排除 APNs 路由",[row("排除 APNs 路由","toggle","关",layer=A,subhub="device")],"开启后，Apple 推送通知直接到达本设备，不经过代理。下次连接时生效")],
 ["more-vpn.png","more-vpn_2.png"],kind="form",note="和 Surge「高级设置 › 路由」的 include-* 是同一组 iOS 能力，但这里存在本机，不在配置里；三个「包括」开关在「包括所有网络」关闭时是灰的"))
S.append(screen("more-client",M+["客户端设置"],"客户端设置",PUSH,[
 group(None,[row("切换节点时断开连接","toggle","开",layer=A,subhub="device")],"立即把实时流量切到新选中的节点。"),
 group(None,[row("UDP 兜底","disclosure","关闭",layer=A,subhub="device")],"HTTP 与 HTTPS 代理没有 UDP 传输通道。若不设置，命中规则但出口承载不了的流量会穿过全部规则，带着你自己的地址经 DIRECT 出门。"),
 group("流量统计",[row("网速单位","popup","比特（Mbps）⌃⌄",layer=A,subhub="device"),row("仅统计代理流量","toggle","关",layer=A,subhub="device")],"关闭时显示全部流量。开启后隐藏直连出网的流量（最终出站为 DIRECT），面板数字即代表代理用量。刷新统计期间 VPN 保持连接。"),
 group("自动更新",[row("计费网络下允许自动更新","toggle","开",layer=A,subhub="device"),row("低数据模式下允许自动更新","toggle","开",layer=A,subhub="device")],"配置链接与资源会按各自的周期更新，不挑网络。关掉其中一项，就会在那类网络上暂缓更新。"),
 group("下载身份",[row("链接兼容性","popup","Clash（默认）⌃⌄",layer=A,subhub="device",note="影响 SubHub 订阅请求的 User-Agent")],"下载配置链接时发送这个身份；配置没写自己的「下载时的 UA」时，它的节点集合、规则集等下载也用它。推荐 Clash；FlClash 用于按客户端名识别的面板。"),
 group(None,[row("外部控制器","disclosure","使用配置","more-client-controller",layer=A,subhub="partial",note="「使用配置」时跟随配置里的 external-controller（intent clash_external_controller）")],"让 Mac 上的 clash-cli 和 AI 助手控制这台设备上的 Clash。"),
 group("信任",[row("证书库","popup","平台默认 ⌃⌄",layer=A,subhub="device")],"使用平台自身的信任，不做任何改变。"),
 group("延迟测试 URL",[row("延迟测试 URL","textfield","https://www.gstatic.com/generate_204",layer=A,subhub="device")],"用于节点延迟测试。留空则恢复默认端点。")],
 ["more-client_1.png","more-client_2.png"],[("UDP 兜底","子页未进")],kind="form"))
S.append(screen("more-client-controller",M+["客户端设置","外部控制器"],"外部控制器",PUSH,[
 group(None,[row("使用配置","segmented","✓",layer=A,subhub="partial",maps_to=iv("clash_external_controller")),row("本机","segmented",layer=A,subhub="device"),row("局域网","segmented",layer=A,subhub="device")],"让 Mac 上的 clash-cli 和 AI 助手控制这台设备上的 Clash。")],
 ["more-client-controller.png"],kind="picker",note="单选，没改；这一页不显示 Secret"))
S.append(screen("more-appearance",M+["外观"],"外观",PUSH,[
 group(None,[row("语言","disclosure","跟随系统",layer=A,subhub="device")],"更改会立即生效。“跟随系统” 使用 iOS 设置中选择的语言。"),
 group("主题",[row("跟随系统 / 浅色 / 深色","segmented","跟随系统",layer=A,subhub="device"),row("强调色","popup","系统动态 ⌃⌄",layer=A,subhub="device"),row("深色模式使用纯黑背景","toggle","关",layer=A,subhub="device")],"系统动态使用应用的原生自适应强调色。纯黑只改变深色背景，并保留语义表面与对比度。"),
 group(None,[row("文字大小跟随 iOS 动态字体与辅助功能设置。","info","ⓘ 图标",layer=A,subhub="na")])],["more-appearance.png"]))
S.append(screen("more-geo",M+["Geo 资源"],"资源",PUSH,[
 group(None,[row("同步全部 Geo 资源","action",layer=X,subhub="na")],"自动更新和下载地址在配置编辑器里改。\n上次完整刷新：从未。"),
 group("GEOIP",[row("GeoIP.dat","card","16.1 MB · 1天前；下载地址；「同步」按钮",layer=P,subhub="none",maps_to="geox-url.geoip")]),
 group("GEOSITE",[row("GeoSite.dat","card","4.0 MB · 1天前",layer=P,subhub="none",maps_to="geox-url.geosite")]),
 group("MMDB",[row("geoip.metadb","card","8.1 MB · 1天前",layer=P,subhub="none",maps_to="geox-url.mmdb")]),
 group("ASN",[row("ASN.mmdb","card","11.5 MB · 1天前",layer=P,subhub="none",maps_to="geox-url.asn")])],
 ["more-geo.png","more-geo_2.png"],[("同步按钮","动作")],note="页标题是「资源」而不是「Geo 资源」；URL 用等宽小字"))
S.append(screen("more-storage",M+["存储空间"],"存储空间",PUSH,[
 group("本机占用",[row(n,"readonly",v,layer=A,subhub="na") for n,v in [("总计","42.1 MB"),("配置","184 KB"),("节点与规则库","53 KB；副标题「节点与规则库在每次写入时自动回收未使用的数据。」"),("Geo 数据","41.8 MB"),("规则集与节点集缓存","0 字节"),("Geo 数据缓存","0 字节"),("日志","0 字节"),("临时文件","0 字节"),("其他","74 KB；副标题「Clash 运行所需的文件，以及已下载的控制台」")]]),
 group("清理",[row("清理未使用数据","action","灰；没有可清理的数据",layer=X,subhub="na")]),
 group("重置本地数据",[row("（未滚到）","action",layer=X,subhub="na")])],["more-storage.png"],[("清理 / 重置","动作")]))
S.append(screen("more-about",M+["关于 Clash"],"关于",PUSH,[
 group(None,[row("Clash","card","由 Clash 驱动；版本 1.0.14 (178)；提交哈希",layer=A,subhub="na")],"Clash 系列客户端，由 Clash 内核驱动。"),
 group("链接",[row(n,"link",v,layer=X,subhub="na") for n,v in [("使用指南","clash.md/zh/guide"),("Telegram","t.me/clashbyclash"),("在 X 关注我","@ClashbyClash"),("源代码仓库","github.com/ProjectClash/Clash-Client"),("建议和吐槽","GitHub Issues")]]),
 group("组件",[row("Clash 内核","link","1.19.33；副标题「承载流量的开源内核」",layer=A,subhub="na")])],["more-about.png"],[("链接","外链")]))

dump("clash",{"version":"1.0.14 (178)，内核 1.19.33","app_name":"Clash（ProjectClash）","substitute_for":"Clash Mi —— 手机上没找到 Clash Mi，用这个 mihomo 系客户端代替；不是简报指定的 App","captured":"2026-11-11","device":"iPhone 17 Pro（镜像窗口）","current_profile":"<lan-host>(3)（实验配置）","vpn_state":"未连接（未改动）","tabs":["首页","工具","更多"],
 "legend":{"layer":{"profile":"写进配置","app":"只在本机","action":"动作"},"subhub":REL}},S)
