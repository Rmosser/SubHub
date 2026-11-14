"""Clash Mi 1.0.31.1703（mihomo 1.19.32）只读遍历，2026-11-11。
Clash Mi 的「核心设置」是 App 本机的一层覆写：多数分区有「覆写」开关，开着时用这里的值盖过配置文件里的同名字段。
所以这里的行一律 layer=app；SubHub 订阅里也写了同名字段的，subhub=device 并在 note 里写清楚会被盖掉。"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import row, group, screen, dump

P = "profile"; A = "app"; X = "action"
def iv(k): return f"intent {k}"
OVR = "覆写开时盖过订阅里的同名字段"
def ov(label, control, value, key, intent=None, note=None, to=None):
    n = OVR + ("；SubHub 订阅里也写了这个字段" if intent else "")
    if note: n += "；" + note
    return row(label, control, value, to, maps_to=(iv(intent) + " → " + key) if intent else key, layer=A, subhub="device", note=n)

HOME = ["首页"]
S = []
S.append(screen("home", HOME, "Clash Mi", {}, [
    group(None, [row("未连接", "toggle", "关", layer=X, subhub="na", note="连接 VPN 的总开关；没拨"),
                 row("分流模式", "segmented", "规则（选中）/ 全局 / 直连", maps_to="mode", layer=A, subhub="unverified", note="未核对是否盖过订阅里的 mode"),
                 row("我的配置", "disclosure", "+ ›", "profiles", layer=X, subhub="na", note="+ 是导入，没点")]),
    group(None, [row("应用设置", "disclosure", None, "app-settings", layer=A, subhub="na"),
                 row("核心设置", "disclosure", None, "core-settings", layer=A, subhub="na"),
                 row("核心日志", "disclosure", None, layer=A, subhub="na"),
                 row("备份与同步", "disclosure", None, layer=A, subhub="na"),
                 row("帮助", "disclosure", None, layer=A, subhub="na"),
                 row("关于", "disclosure", None, "about", layer=A, subhub="na")])],
    ["home.png"], [("核心日志", "运行日志，含访问记录"), ("备份与同步", "可能涉及 iCloud / WebDAV 账户"), ("帮助", "外链")]))

S.append(screen("profiles", HOME + ["我的配置"], "我的配置", {"left": "返回", "right": "☁︎ 下载 / +"}, [
    group(None, [])], ["profiles.png"], [("右上 ☁︎ / +", "导入动作")], note="刚安装，列表为空"))

CS = HOME + ["核心设置"]
S.append(screen("core-settings", CS, "核心设置", {"left": "返回", "right": "📄（查看生成的配置，未进：含 Secret）"}, [
    group(None, [row("重置", "disclosure", None, layer=X, subhub="na", note="重置动作，没点")]),
    group(None, [ov("外部控制", "textfield", "127.0.0.1:9090", "external-controller", "clash_external_controller", "无覆写开关"),
                 ov("Secret", "textfield", "<redacted>", "secret", "clash_secret", "无覆写开关；截图已涂黑"),
                 ov("混合代理端口", "textfield", "7890", "mixed-port", "clash_mixed_port", "无覆写开关"),
                 ov("日志等级", "popup", "error ▾", "log-level", "clash_log_level", "无覆写开关"),
                 row("Pprof Address", "textfield", "127.0.0.1:4578（灰，占位）", maps_to="（调试用，非 mihomo 配置键）", layer=A, subhub="none"),
                 row("Pprof", "disclosure", None, layer=A, subhub="none")]),
    group(None, [ov("Unified Delay", "popup", "不覆写 ▾", "unified-delay"),
                 ov("IPv6", "popup", "禁用 ▾", "ipv6", "clash_ipv6"),
                 row("TUN", "disclosure", None, "core-tun", maps_to="tun", layer=A, subhub="device"),
                 row("Geo RuleSet", "disclosure", None, "core-geo-ruleset", maps_to="geox-url / geo-update-interval", layer=A, subhub="device")]),
    group(None, [row("分流模板", "disclosure", None, "core-diversion-template", layer=A, subhub="none")]),
    group(None, [row("覆写", "disclosure", "内置-覆写 ›", "core-override", layer=A, subhub="device", note="选「内置-不覆写」时本页各分区不生效")]),
    group(None, [ov("TCP并发握手", "popup", "不覆写 ▾", "tcp-concurrent", "clash_tcp_concurrent"),
                 ov("TCP保活时间间隔", "textfield", "30 s（下划线可点）", "keep-alive-interval"),
                 ov("TLS全局指纹", "popup", "chrome ▾", "global-client-fingerprint")]),
    group(None, [row("局域网设备接入", "disclosure", None, "core-lan-access", maps_to="allow-lan / bind-address / authentication", layer=A, subhub="device")]),
    group(None, [row("DNS", "disclosure", None, "core-dns", maps_to="dns", layer=A, subhub="device"),
                 row("NTP", "disclosure", None, "core-ntp", maps_to="ntp", layer=A, subhub="none"),
                 row("TLS", "disclosure", None, "core-tls", maps_to="tls", layer=A, subhub="none"),
                 row("嗅探", "disclosure", None, "core-sniffer", maps_to="sniffer", layer=A, subhub="device")])],
    ["core-settings_1.png", "core-settings_2.png"], [("重置", "动作"), ("右上 📄", "显示生成的配置原文，含 Secret"), ("Pprof", "调试")],
    note="每行左侧 ⓘ 是说明气泡；所有下拉没展开，值从行尾读出"))

def ovt(label, value, key, intent=None, note=None):
    return ov(label, "toggle", value, key, intent, note)
S.append(screen("core-tun", CS + ["TUN"], "TUN", {"left": "返回"}, [
    group(None, [row("覆写", "toggle", "开", maps_to="（本分区覆写总开关）", layer=A, subhub="device"),
                 ovt("启用", "开", "tun.enable", "clash_tun_enable"),
                 ov("IPv4地址段", "textfield", "172.19.0.1/30", "tun.inet4-address"),
                 ov("网络栈", "popup", "gvisor ▾", "tun.stack", "clash_tun_stack"),
                 ov("MTU", "textfield", "1280", "tun.mtu"),
                 ovt("DNS劫持", "开", "tun.dns-hijack", "clash_tun_dns_hijack"),
                 ovt("严格路由", "关", "tun.strict-route", "clash_tun_strict_route"),
                 ovt("默认路由", "开", "tun.auto-route", "clash_tun_auto_route"),
                 ovt("includeAllNetworks", "关", "（iOS NEPacketTunnel 选项）"),
                 ovt("excludeLocalNetworks", "关", "（iOS NEPacketTunnel 选项）"),
                 ovt("excludeCellularServices", "关", "（iOS NEPacketTunnel 选项）"),
                 ovt("excludeAPNs", "关", "（iOS NEPacketTunnel 选项）"),
                 ovt("excludeDeviceCommunication", "关", "（iOS NEPacketTunnel 选项）"),
                 ovt("enforceRoutes", "关", "（iOS NEPacketTunnel 选项）"),
                 ovt("ICMP 转发", "关", "tun.disable-icmp-forwarding（取反）")]),
    group(None, [ovt("附加HTTP代理到VPN", "关", "（iOS 系统 HTTP 代理）"),
                 row("允许绕过HTTP代理的域名", "disclosure", None, maps_to="（iOS 系统代理例外）", layer=A, subhub="none"),
                 row("隐藏VPN图标", "toggle", "关", layer=A, subhub="none")])],
    ["core-tun_1.png", "core-tun_2.png"]))

S.append(screen("core-geo-ruleset", CS + ["Geo RuleSet"], "Geo RuleSet", {"left": "返回"}, [
    group(None, [ov("更新时间间隔", "textfield", "2 d", "geo-update-interval"),
                 row("使用代理下载Geo RuleSet", "toggle", "开", layer=A, subhub="none"),
                 ov("GeoSite", "textfield", "https://raw.githubuse…（截断）", "geox-url.geosite"),
                 ov("GeoIp", "textfield", "https://raw.githubuse…（截断）", "geox-url.geoip")])],
    ["core-geo-ruleset.png"], note="无覆写开关"))

S.append(screen("core-diversion-template", CS + ["分流模板"], "分流模板", {"left": "返回"}, [
    group(None, [row("规则提供者", "disclosure", None, maps_to="rule-providers 模板", layer=A, subhub="none"),
                 row("规则模板", "disclosure", None, maps_to="rules 模板", layer=A, subhub="none"),
                 row("代理组模板", "disclosure", None, maps_to="proxy-groups 模板", layer=A, subhub="none")])],
    ["core-diversion-template.png"], [("三个子页", "时间优先，未进")]))

S.append(screen("core-override", CS + ["覆写"], "覆写", {"left": "返回", "right": "☁︎ 下载 / +"}, [
    group(None, [row("内置-覆写", "radio", "选中（蓝色），副标题 Buildin", layer=A, subhub="device"),
                 row("内置-不覆写", "radio", "副标题 Buildin", layer=A, subhub="device")])],
    ["core-override.png"], [("点选行", "会切换覆写方案"), ("☁︎ / +", "导入动作")]))

S.append(screen("core-lan-access", CS + ["局域网设备接入"], "局域网设备接入", {"left": "返回"}, [
    group(None, [row("覆写", "toggle", "关", layer=A, subhub="device"),
                 ovt("启用", "关", "allow-lan", "clash_allow_lan"),
                 ov("IP", "popup", "空 ▾", "bind-address"),
                 ov("授权", "textfield", "空（占位 username:pa…）", "authentication", note="有值时属敏感值")])],
    ["core-lan-access.png"]))

S.append(screen("core-dns", CS + ["DNS"], "DNS", {"left": "返回"}, [
    group(None, [row("覆写", "toggle", "开", layer=A, subhub="device"),
                 ovt("启用", "开", "dns.enable", "clash_dns_enable"),
                 ov("监听地址", "textfield", "0.0.0.0:53（灰）", "dns.listen", "clash_dns_listen"),
                 ovt("DoH H3优先", "开", "dns.prefer-h3"),
                 ovt("使用系统Hosts", "开", "dns.use-system-hosts"),
                 ovt("使用Hosts", "开", "dns.use-hosts", "clash_dns_use_hosts")]),
    group(None, [ov("hosts", "disclosure", None, "hosts")]),
    group(None, [ov("增强模式", "popup", "fake-ip ▾", "dns.enhanced-mode", "clash_dns_enhanced_mode"),
                 ov("fake-ip 过滤模式", "popup", "blacklist ▾", "dns.fake-ip-filter-mode", "clash_dns_fake_ip_filter_mode"),
                 ov("fake-ip 过滤", "disclosure", None, "dns.fake-ip-filter", "clash_fake_ip_filter")]),
    group(None, [ovt("遵守[rules]规则", "关", "dns.respect-rules", "clash_dns_respect_rules"),
                 ov("默认 域名解析服务器", "disclosure", None, "dns.default-nameserver", "clash_dns_default_nameserver"),
                 ov("域名解析服务器", "disclosure", None, "dns.nameserver", "clash_dns_nameserver"),
                 ov("代理 域名解析服务器", "disclosure", None, "dns.proxy-server-nameserver", "clash_dns_proxy_server_nameserver"),
                 ov("直连 域名解析服务器", "disclosure", None, "dns.direct-nameserver", "clash_dns_direct_nameserver"),
                 ov("Fallback 域名解析服务器", "disclosure", None, "dns.fallback", "clash_dns_fallback"),
                 ovt("Fallback GeoIp", "关", "dns.fallback-filter.geoip"),
                 ov("Fallback GeoIp 代码", "textfield", "空", "dns.fallback-filter.geoip-code")])],
    ["core-dns_1.png", "core-dns_2.png"], [("hosts / fake-ip 过滤 / 各解析服务器子页", "时间优先，未进")],
    note="没看到 fake-ip-range 与 nameserver-policy 的行（SubHub 有 clash_dns_fake_ip_range / clash_dns_nameserver_policy）"))

S.append(screen("core-ntp", CS + ["NTP"], "NTP", {"left": "返回"}, [
    group(None, [row("覆写", "toggle", "关", layer=A, subhub="none"),
                 ovt("启用", "关", "ntp.enable"),
                 ov("服务器", "textfield", "空（占位 必填）", "ntp.server"),
                 ov("端口", "textfield", "空（占位 必填）", "ntp.port")])], ["core-ntp.png"]))

S.append(screen("core-tls", CS + ["TLS"], "TLS", {"left": "返回"}, [
    group(None, [row("覆写", "toggle", "关", layer=A, subhub="none"),
                 ov("证书", "textfield", "空", "tls.certificate"),
                 ov("私钥", "textfield", "空", "tls.private-key", note="有值时属敏感值"),
                 row("自定义证书", "disclosure", None, maps_to="tls.custom-certifactes", layer=A, subhub="none")])], ["core-tls.png"]))

S.append(screen("core-sniffer", CS + ["嗅探"], "嗅探", {"left": "返回"}, [
    group(None, [row("覆写", "toggle", "关", layer=A, subhub="device"),
                 ovt("启用", "关", "sniffer.enable", "clash_sniffer_enable"),
                 ovt("覆盖", "关", "sniffer.override-destination")])], ["core-sniffer.png"]))

S.append(screen("app-settings", HOME + ["应用设置"], "应用设置", {"left": "返回"}, [
    group(None, [row("重置", "disclosure", None, layer=X, subhub="na", note="动作，没点")]),
    group(None, [row("语言", "disclosure", "简体中文 ›", layer=A, subhub="none"),
                 row("主题", "popup", "light ▾", layer=A, subhub="none"),
                 row("主屏", "disclosure", None, layer=A, subhub="none"),
                 row("跟随屏幕旋转", "toggle", "关", layer=A, subhub="none")]),
    group(None, [row("日志等级", "popup", "warning ▾", layer=A, subhub="none", note="App 自身日志，不是内核 log-level")]),
    group(None, [row("UserAgent", "textfield", "ClashMeta/1.19.32; m…（截断）", maps_to="订阅下载 UA", layer=A, subhub="device", note="SubHub 按 UA 识别客户端时会看到这个值")]),
    group(None, [row("延迟测试URL", "textfield", "https://www.gsta…（截断）", layer=A, subhub="none"),
                 row("延迟测试超时(ms)", "textfield", "5000", layer=A, subhub="none")]),
    group(None, [row("使用在线面板", "toggle", "关", layer=A, subhub="none"),
                 row("本地面板端口", "textfield", "7066", layer=A, subhub="none")]),
    group(None, [row("始终开启连接", "toggle", "关", layer=A, subhub="none", note="按需连接")])],
    ["app-settings.png"], [("重置", "动作"), ("语言 / 主屏", "选择页，未进")]))

S.append(screen("about", HOME + ["关于"], "关于", {"left": "返回"}, [
    group(None, [row("名称", "label", "Clash Mi", layer=A, subhub="na"),
                 row("版本", "label", "1.0.31.1703", layer=A, subhub="na"),
                 row("核心", "label", "mihomo 1.19.32", layer=A, subhub="na")])], ["about.png"]))

S.append(screen("first-launch", ["首次启动"], "Your Privacy Comes First", {}, [
    group(None, [row("允许 “Clash Mi” 使用无线数据？", "system-alert", "无线局域网与蜂窝网络 / 仅限无线局域网 / 不允许", layer=A, subhub="na",
                     note="用户 2026-11-11 指示选「无线局域网与蜂窝网络」"),
                 row("Accept & Continue", "button", None, layer=X, subhub="na",
                     note="用户同意点；实际选完系统弹窗后 App 直接进了核心设置，这个按钮没点到")])],
    ["first-launch-cellular-prompt.png"]))

# app-guide-clash-mi.md 的实验结论（证据编号见 lab-evidence-2026-11.md）：哪些项在「内置-不覆写」时仍压过订阅
GUIDE = {("core-settings","外部控制"):"app-guide：内置-不覆写时仍覆盖 E-M-006",
         ("core-settings","Secret"):"app-guide：内置-不覆写时仍覆盖 E-M-006",
         ("core-settings","混合代理端口"):"app-guide：端口在内置-不覆写时仍被改写 E-M-022",
         ("core-settings","日志等级"):"app-guide：固定覆写为 error，订阅写 info 也没用 E-M-022",
         ("core-settings","IPv6"):"app-guide：「禁用」在内置-不覆写时仍压过订阅，IPv6 节点不可用 E-M-022/023/024",
         ("core-settings","覆写"):"app-guide：内置-覆写会把订阅的 dns 整段、fake-ip-range、fake-ip-filter 换掉；SubHub 导入说明应让用户选「内置-不覆写」 E-M-008/011",
         ("core-settings","TLS全局指纹"):"app-guide：只在内置-覆写时写入，对 ≥1.19.27 内核无效 E-M-102",
         ("core-tun","网络栈"):"app-guide：stack 在内置-不覆写时仍覆盖 E-M-011",
         ("core-tun","MTU"):"app-guide：mtu 在内置-不覆写时仍覆盖 E-M-011",
         ("core-tun","DNS劫持"):"app-guide：dns-hijack 在内置-不覆写时仍覆盖 E-M-011",
         ("core-tun","IPv4地址段"):"app-guide：运行时取 fake-ip-range 的前 /30，与界面值不一致 E-M-006",
         ("core-dns","启用"):"app-guide：内置-不覆写时订阅 DNS 原样保留 E-M-011"}
for sc in S:
    for g in sc["groups"]:
        for r in g["rows"]:
            k=(sc["id"], r["label"])
            if k in GUIDE: r["note"] = (r.get("note","") + "；" if r.get("note") else "") + GUIDE[k]

# 行首 ⓘ（说明气泡）标记，按截图记录
INFO_NO = {"重置", "Pprof Address", "Pprof", "分流模板", "局域网设备接入", "覆写", "语言", "主题", "主屏", "跟随屏幕旋转", "日志等级",
           "UserAgent", "延迟测试URL", "延迟测试超时(ms)", "使用在线面板", "本地面板端口", "始终开启连接", "默认路由", "IPv4地址段", "MTU",
           "附加HTTP代理到VPN", "允许绕过HTTP代理的域名", "隐藏VPN图标", "更新时间间隔", "使用代理下载Geo RuleSet", "GeoSite", "GeoIp", "hosts"}
for sc in S:
    if sc["id"].startswith("core-") or sc["id"] == "core-settings":
        for g in sc["groups"]:
            for r in g["rows"]:
                r["info_icon"] = not (r["label"] in INFO_NO or (r["label"] == "覆写" and sc["id"] != "core-settings"))
for sc in S:
    if sc["id"] == "core-settings":
        for g in sc["groups"]:
            for r in g["rows"]:
                if r["label"] in ("覆写", "日志等级"): r["info_icon"] = True
dump("clash-mi", {"version": "1.0.31.1703，内核 mihomo 1.19.32", "developer": "Supernova Nebula LLC",
                  "captured": "2026-11-11", "device": "iPhone 17 Pro，iOS 27.2.1",
                  "state": "新装，未导入配置，未连接；覆写方案 = 内置-覆写"}, S)
