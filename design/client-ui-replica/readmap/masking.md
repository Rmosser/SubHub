# 打码规则

依据：`app/services/subscription_builder.py`（`_surge_proxy_line`、`_shadowrocket_proxy_line`、`_surge_wireguard_section_lines`、Clash payload）和 `app/services/subscription_urls.py`。

## 行为

- 默认打码。打码后显示固定 6 个圆点，不透露原值长度。
- 点单个值才显示这一个值；折叠所在段、切换客户端或离开页面后恢复打码。
- 原文行本身能点（能走到手机上的行、段头行、文件头）时，打码片段不是嵌在里面的按钮：点在片段上只显示它，点在别处照旧走到手机；键盘从这一行按 Tab 到紧跟它的「显示密文」按钮（平时看不见，获得焦点才出现），一次显示或收起这一行的全部值。
- 手机行和原文是同一份状态：`bind.mask: true` 的手机行和它对应的原文片段一起显示、一起打码。
- 打码在渲染层做（把一行切成片段再画），不改原文字符串。行号、`bind` 的解析、连线都用原值。
- 打码的值不进 URL、不进 `title` / `aria-label`。

## Surge / Shadowrocket（INI）

| 位置 | 识别规则 | 打码范围 |
|---|---|---|
| 第 1 行 `#!MANAGED-CONFIG <url> …` | 行首匹配 | 按下面「URL」处理 |
| `[Proxy]` 行里的具名参数 | 逗号分隔后，键名（不分大小写）属于：`password`、`uuid`、`token`、`username`（Surge 的 vmess 把 UUID 写在这里）、`obfs-password`、`psk`、`pre-shared-key`、`private-key`、`privateKey`、`shortId` | `=` 后面的值 |
| `[Proxy]` 行的位置参数 | 协议是 `http`、`https`、`socks5` 时，第 4、5 个字段（用户名、密码） | 整个字段 |
| `[WireGuard <名字>]` 段（Surge） | 键 `private-key`；`peer = (…)` 里的 `preshared-key` | 值 |
| `[General] http-api` | 值里有 `@` | `@` 之前的部分 |
| `[General] wifi-access-http-auth` | 键名匹配（SubHub 现在不写，防御性规则） | 整个值 |
| `[MITM] ca-passphrase`、`ca-p12` | 键名匹配（SubHub 现在不写，防御性规则） | 整个值 |
| `[Script]` 行的 `argument=` | 键名匹配 | 值 |
| 任何位置的 URL | 见下 | 见下 |

不打码：`publicKey` / `public-key`（公钥）、服务器地址、端口、`sni`。

## Mihomo（YAML）

| 位置 | 识别规则 | 打码范围 |
|---|---|---|
| 顶层 `secret:` | 键路径 | 值 |
| 顶层 `authentication:` | 列表每一项（`user:pass`） | 整项 |
| `tls.private-key` | 键路径 | 值 |
| `proxy-providers.*.url`、`rule-providers.*.url` | 键路径 | 按「URL」处理 |
| `proxies[*]`（主文件一般没有，节点在 provider 里；防御性规则） | 键名属于：`password`、`uuid`、`token`、`psk`、`pre-shared-key`、`private-key`、`obfs-password`、`auth`、`auth-str`、`short-id` | 值 |

不打码：`external-controller`（只是地址）。

## URL（三端通用）

对原文里任何 `http(s)://…`：

1. 路径 `/sub/device/<id>/…` 里的 `<id>` 段。这是设备的公开订阅 ID，拿到它就能拉订阅。
2. 查询参数 `sig` 的值。`rev`、`exp` 不打码。
3. 其他查询参数，键名匹配 `token|key|secret|sig|auth|password|passwd` 的值。
4. `user:pass@host` 形式的 userinfo。

## 认不出来的

- DoH 地址里的个人 ID（例如 `https://dns.nextdns.io/<id>`）没有通用特征，不处理。
- `[Script]` 的 `script-path`、`[URL Rewrite]` 的替换地址如果把密钥写在路径里，只能被上面第 3、4 条碰巧盖住。
- 节点名里若带个人信息，不处理。
