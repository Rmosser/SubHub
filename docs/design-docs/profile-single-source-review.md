# Profile Single-Source Review

适用范围：`/manage/profile` 的 Profile family、能力矩阵、editor schema、保存路径与投影预览。

本审计顺序：先固定 canonical domain model，再审 capability matrix，最后检查 UI / API / 保存路径。

## Canonical Domain Model

- `excluded-routes`
  - canonical truth：IP / CIDR 绕行
  - 目标分类：`shared`
  - 结论：[已确认]

- `skip-proxy`
  - canonical truth：域名 / 主机绕行意图
  - 目标分类：`shared + adapted`
  - Mihomo 只接收投影：`rules (DIRECT)`，以及 fake-ip 模式下的 `dns.fake-ip-filter`
  - 结论：[已确认] / Shadowrocket 侧补充证据为 [已确认：用户实机验证]

- `control-api-access`
  - canonical truth：控制面地址与密钥
  - 目标分类：`shared`
  - Mihomo `external-controller / secret` 与 Surge `http-api / http-api-secret` 视为同一控制面语义
  - 结论：[已确认]

## Capability Matrix

| family | GP-16 结论 | 证据等级 | review 级别 | 备注 |
| --- | --- | --- | --- | --- |
| `excluded-routes` | `shared` | [已确认] | `info` | 三端都表达同一类 TUN 排除路由语义；保存时强同步。 |
| `ipv6-policy` | `shared` | [已确认] / Shadowrocket 关闭：[实机验证：不工作] | `warning` | 三端共用一份开关值。Shadowrocket 2.2.93 的 `ipv6 = false` 运行时不生效，仍解析 AAAA、接管 IPv6 并按规则转发（E-R-028，LINT-ROK-207）；界面如实提示，限制 IPv6 只能靠规则。 |
| `control-api-access` | `shared` | [已确认] | `info` | 统一为一份 controller endpoint / secret 真相。 |
| `skip-proxy` | `shared + adapted` | [已确认] / [已确认：用户实机验证] | `info` | Surge / Shadowrocket 共用一份域名 / 主机 truth；Mihomo 只保留 adapted projection。 |
| `real-host-dns` | `blocked` | [待验证] / [证据未覆盖，需补充研究] | `warning` | Surge / Shadowrocket `always-real-ip` 与 Mihomo fake-ip escape 语义接近，但字段级稳定语义与运行边界仍不足以强制共享。 |
| `host-records` | `blocked` | [待验证] / [证据未覆盖，需补充研究] | `warning` | `[Host]` 与 Mihomo `hosts` 仍需继续补证，暂不合并为单一真相。 |
| `mihomo-runtime-native` | `standalone` | [已确认] | `info` | Mihomo 原生运行时字段，不能伪共享到 Surge / Shadowrocket。 |
| `mihomo-profile-store` | `standalone` | [已确认] | `info` | 仅 Mihomo profile persistence。 |
| `mihomo-external-ui` | `standalone` | [已确认] | `info` | 仅 Mihomo external-ui bundle 配置。 |
| `surge-runtime-native` | `standalone` | [已确认] | `info` | Surge 原生 runtime / policy tuning，不与 Mihomo 混用。 |
| `mihomo-dns-behavior` | `standalone` | [已确认] | `info` | Mihomo `dns/tun/sniffer` 联动明显，不能按 UI 字段名做伪共享。 |
| `mihomo-dns-upstreams` | `standalone` | [已确认] | `info` | Mihomo DNS upstream DSL 为真规格。 |
| `url-rewrite` | `standalone` | [已确认] / Shadowrocket 运行边界仍有 [待验证] 部分 | `info` | Mihomo 无等价内核能力；Surge / Shadowrocket 也不是同一文本语义。 |
| `map-local` | `standalone` | [已确认] / Shadowrocket 仅 [已确认：实机导出] + 部分 [待验证] | `info` | 保留单端入口，并明确 Shadowrocket 只按受限能力审核。 |
| `script` | `standalone` | [已确认] | `info` | Surge / Shadowrocket 的 HTTP interception script 语义不能抽成共享字段。 |
| `mitm` | `standalone` | [已确认] / Shadowrocket 部分仅 [已确认：UI存在] | `info` | MITM 主机名、证书链、端口范围与运行前提不同，不强行共享。 |

## 意图阶段补充

上表记录 GP-16 的保存与编辑器机制。派生意图阶段依据运行证据把 IPv6 和 skip-proxy 的跨端等价性保守登记为 blocked；保存和界面不变。完整逐字段事实以 [意图登记表](intent-inventory.md) 为准，设计见 [配置意图](configuration-intent.md)。共用存储值不等于运行语义已证明一致。

## Review Findings

### `error`

- `skip-proxy` 在 GP-16 落地前同时保留了 `surge_native / shadowrocket_experimental / mihomo_split` 三套入口，会导致“同一绕行意图”在不同客户端卡片里分别维护。现在已修复为单一 truth，并把 `CIDR/IP` 迁回 `excluded-routes`。
- `control-api-access` 在 GP-16 落地前让 Surge `http-api` 与 Mihomo `external-controller` 分别维护，违背“控制面地址与密钥的单一语义来源”。现在已修复为共享 family。

### `warning`

- `real-host-dns` 目前只能保守写成 `blocked`。已有证据能证明能力存在，但还不足以把 Surge / Shadowrocket / Mihomo 的字段级语义全部升级成“单一真相已确认”。
- `host-records` 同样保持 `blocked`。如果后续要合并，必须先补齐 Shadowrocket 文本字段与 Mihomo `hosts` 运行语义的稳定证据。

### `info`

- 本轮没有保留新的 `fatal` 级问题；已实现范围内，Profile family 的共享口径已经按 GP-16 收敛。
- 共享 family 的写路径现在做两件事：
  - 先把旧 `skip-proxy` 里的 `CIDR/IP` 渐进迁入 `excluded-routes`
  - 再把 `shared` family 的镜像 key 强同步，避免旧数据长期分叉
- UI 口径同步更新为：
  - `skip-proxy` 主卡只编辑共享 truth
  - Mihomo 只显示生成投影卡
  - 预览显式展示“哪些条目会转入 Excluded Routes”

第 2 轮进一步收紧意图层归类：排除路由按 Shadowrocket 待验证/Surge 仅导出的证据改为 blocked；Surge HTTP API 和 Mihomo controller 作为各自 standalone 接口。上文 GP-16 的存储镜像规则仍然保留，不能再作为运行语义等价的证明。
