# 配置意图与三端兼容投影（第 1 阶段）

本阶段把已读取的设置和分流声明冻结为 `ConfigurationIntent`，再生成 Surge、Mihomo、Shadowrocket 及随订阅下发的文件。数据库、保存路径、编辑器、CLI 均不变化；目标是固定期望状态及差异，并逐字节保留已批准的设备输出。它不是 Agent 提案或批准接口，也不开放 Agent 代批。

## 数据流与边界

`存储读取 → 既有校验/规范化 → derive_configuration_intent → 冻结期望状态 → project_configuration_intent → 既有客户端编译器 → 文本/资产`

- `app/services/configuration_intent.py` 定义模型、派生、投影和管理诊断；没有存储依赖、网络请求、LLM、时钟或随机源。
- `ConfigurationIntent.values` 以登记表的 `canonical_key` 聚合已有共享值；`compatibility_overrides` 显式冻结历史镜像差异。读取时不执行 harmonize、迁移或回写，不能因某端能力不足改变期望值。
- `_policy_json` 冻结现有 `PolicyIR`，含节点、规则、来源、分类、契约、池、默认去向、版本/下发元数据、macOS 模板等。投影重建独立对象，不另建一套分流模型，也不修改缓存中的 IR。
- 派生入口自行编译一次并冻结结果及既有诊断；可选 compiled_rules 仅用于一致性校验，不一致即拒绝。`ip_resolution` 绑定含条件、来源、目标和选项的稳定规则身份；索引仅作描述，不用于匹配。它记录顶层/逻辑位置、明确选项及各端匹配前 DNS 策略。`client-default` 表示允许客户端按既有路径处理，不承诺一定查询或命中。逻辑子表达式保留源文本，不继承顶层 CIDR 默认。
- 模型可经 `to_dict/from_dict` 做 JSON 往返。内部快照可能包含节点凭据，**不增加返回该快照的 HTTP API**。已有管理接口权限与 LazyCat 用户隔离不变。
- 节点在真实下发路径中先经存储的 JSON 序列化，再从存储读取进入渲染。快照容许 Infinity/NaN；直接把 YAML 解析出的 `date`、`bytes` 等非 JSON 类型交给内部 builder 会抛 `TypeError: Unsupported intent value: <类型>`，不支持绕过存储的保存前预览。此边界由回归测试固定，不能将它外推为已支持任意 YAML 类型。
- 客户端实际版本、运行日志、探针结果属于观测状态。本阶段不根据观测反改意图，不声称兼容投影等于实机已生效。

原有内部 builder 参数保持可用；三个主 artifact builder 也接受一个冻结的 `intent`。提供 intent 时，它决定 profile、设置、节点和分流，旧的 settings/rules 参数不会覆盖已冻结状态。规则 provider、节点 provider、节点分享导出、Mac overlay 使用同一派生/投影入口。目标 URL、资源 revision、设备标识、渲染模式和下发环境是显式的确定性输入。

## 唯一登记来源与覆盖边界

机读事实登记在 `app/services/intent_registry.json`（由 scripts/intent_registry_spec.json 经 scripts/build_intent_registry.py 生成）；逐项清单由 `scripts/generate_intent_inventory.py` 生成到 [意图投影登记表](intent-inventory.md)。清单包括意图、三端写法/不支持、证据等级与章节或实验编号、归类理由、warning 代码、流量后果和版本约束。生成物一致性由测试强制核对，不能手工维护第二份矩阵。

实际清点为 87 个 Profile 存储 key，覆盖 16 个 family、29 张卡片、全部 schema 输入及镜像 key、capabilities 和专家字段；另外登记 96 个分流声明/上下文字段（含未类型化 PinGroup 的 5 个输入字段）。时间和管理标志也逐项查消费者，不能按字段名字判定为 metadata：CustomRule.created_at 决定冲突规则顺序，owner_scenario_id 决定契约输入范围，两种 migration_warning 决定 overlay 可用性和 needs-rebind 诊断，均归 blocked。新增存储 key、编辑器输入、capability key 或分流 dataclass 字段而未登记时，覆盖测试失败。

第 3 轮 Profile 为 blocked 17、standalone 70；分流按取值/原生平台展开后为 adapted 1、blocked 78、standalone 52、metadata 17，共 148 条，覆盖原有 96 个字段。shared 为 0。metadata 是“管理元数据，不参与投影及诊断”，不借用 adapted；17 项逐项翻转，经 Hub 输入编译和三端 builder 核对。统计单位是字段/key 或显式取值/平台行，不是 family，镜像 key 分别计数。元数据仍可进入边界缓存 revision 指纹；它不是渲染动作，测试固定显式 URL/revision，不能声称修改元数据连缓存标识也不变。

唯一保留的 adapted 是“不由该规则触发 DNS”，不是“不使用已解析 IP”：Mihomo v1.19.33 引 E-M-139；Surge 引 [官方 IP Rules 的 no-resolve 参数](https://manual.nssurge.com/rules/ip.html)，属于文档确认，不冒充 iOS 5.23.0 新实测；Shadowrocket 2.2.93 引 E-R-190，范围为 Safari HTTP 系统代理、节点兜底、无规则集和 skip-proxy。strict 在三端都输出为 fallback 组（成员依次是主池自动组、降级时的备用池自动组和 REJECT 或 DIRECT）；各端只证明 fallback 由首个可用成员承接，主池全部不可用后按失败动作切到后面成员没有直接证据，归 blocked。failover/load-balance 拆成本端原生命名空间，不能用原生能力证明跨端等价。

GP-16 的保存/编辑器共享机制保留；本次不把历史 UI 的 family 标签当成运行等价证明：

- IPv6 仍使用原有镜像写路径，但三端关闭 IPv6 的后果不同，意图归类为 blocked；特别是 Shadowrocket `ipv6=false` 不阻止 AAAA 和 IPv6 转发（E-R-028）。
- skip-proxy 的保存与 Mihomo 适配保留，但 Surge 系统代理绕行、Shadowrocket 隐式 DIRECT 和 Mihomo 显式 DIRECT 不是已证明相同的语义（E-S-171、E-R-168）。因此归类为 blocked，不能因“共用一个值”就宣称流量相同。
- real-host-dns、host-records 延续 blocked。排除路由同样改为 blocked：Shadowrocket 仅待验证，Surge 只有实机导出。控制面接口拆为各自 standalone：Surge HTTP API 和 Mihomo controller/Bearer secret 为不同接口，不再因端口或密钥默认值不同报告共享分叉。
- standalone 按原生字段/DSL 的所属端隔离；两端都具备 Rewrite/MITM，不代表其中一端的原始 DSL 可以直接跨端使用。

## 四层投影差异

| 层 | 保留的边界 |
| --- | --- |
| 语法 | DST-PORT/DEST-PORT、NETWORK/PROTOCOL、YAML/section、Host 通配、API 认证、规则集不带行内策略。 |
| 语义 | IPv6、skip-proxy、真实地址、DNS 联动、UDP 和拒绝变体仍按既有各端行为。 |
| 能力 | Mihomo 无 MITM/HTTP 改包；sniffer/provider DSL 不伪投到其他端；macOS overlay 不当作手机能力。 |
| 下发 | Surge 主文件及 domain-set/rule-set、Mihomo 主文件及 provider/规则文件/离线包、Shadowrocket inline 配置与叶子 URI 分享、Surge Mac include/overlay 各自保留。 |

证据基线为 Skill 的 Surge iOS 5.23.0、Shadowrocket 2.2.93、Mihomo v1.19.33；版本敏感项的 `version_gates` 沿用 Skill 的 min/strict_from/fallback 词汇。本阶段只记录和诊断，不新增会改变历史文件的版本拒绝或删字段门控。未提供设备版本就不能声称任意版本可用。

## IP 匹配前的 DNS 意图

| 规则位置/来源 | Mihomo | Surge | Shadowrocket |
| --- | --- | --- | --- |
| 用户顶层 IP-CIDR / IP-CIDR6 | `never`，沿用补 no-resolve | `client-default`，不补 | `client-default`，不补 |
| 顶层 SRC-IP-CIDR | `never`，沿用整组选项替换成 no-resolve（丢弃其他参数） | 无已验证等价条件，沿用原过滤/诊断 | 保留既有原生行为与待验证范围 |
| GEOIP / IP-ASN | 不补；来源自带保留 | 同左 | 同左；域名是否解析还取决于兜底和接管路径 |
| 逻辑规则内 IP 条件 | 保留原始子条件，不补 | 同左 | 同左 |
| 来源自带 no-resolve | 保留不主动解析意图及原有序列化 | 同左 | 同左 |
| 系统私网规则 | 继续带 no-resolve | 同左 | 同左 |

顶层 CIDR 的 Mihomo 默认由意图投影到编译规则，既有 CIDR 规范化和规则集序列化仍保持不变。规范化/序列化只读取投影后的明确选项，不能再次按客户端和类型推断 no-resolve。修改冻结策略时，主文件及 rule-provider 资产都会跟随。这里的 `never` 是“不由该规则主动触发 DNS”，**不是**“不能利用已有解析结果”，也不是 DNS 隐私保证（E-M-139）。

三端不一致时，`intent-ip-dns-client-default-differs` 说明：Surge 可先解析；Mihomo 的该条 no-resolve 不主动解析；Shadowrocket 在 `FINAL,REJECT` 下不解析、不命中，在代理或 DIRECT 兜底的 Safari HTTP 系统代理路径可解析并命中，其他 TUN/App 组合未证明（E-R-152、E-R-167、E-R-186、E-R-191）。

`intent-ip-only-category-direct-fallback` 针对只有 IP-CIDR/IP-CIDR6/GEOIP/IP-ASN 的非系统分类且显式默认动作为 direct。白话后果必须是条件性的：如果没有可用 IP、禁止解析或客户端不先解析，而且后续也无其他匹配规则，域名请求会落到兜底直连。不能错误地声称 Surge 或 Shadowrocket 的所有域名请求都会漏过 IP 规则。混合分类和系统私网不触发此告警。

## 诊断契约

所有新增诊断都是 `severity=warning`，使用已有 `warnings` 及 `diagnostics.downgraded/pending_validation`；不加入 blockers，不新增 409。

登记表中每个 unsupported/pending_validation 投影（按值/平台的记录分别登记）都有稳定代码及白话后果；代码按能力域、目标、状态稳定，`target` 指明具体字段或对象。设置文案只在 unsupported 时追加目标端的“没有可证明等价投影”，pending_validation 不加。分流证据缺口按声明对象去重计数，显示最多三个具体规则值/契约名；无具体对象不报笼统提示。strict 每端合并为一条，写数量和最多三个契约名，并说明本端缺的证据；只统计本端实际输出为 fallback 组的契约，Surge 把没有可用主池的契约输出为 `select, REJECT`，不计入，一个也没有时不报；Mihomo 端被丢弃的 UID、PASS、PASS-RULE、REMATCH-NAME 合并为一条，写类型数和最多三个类型名；load-balance 仅在参数待验证的 Shadowrocket 报 persistent=1；有原生文档/直接实验的 failover 不再常驻 warning。DSCP、SUB-RULE 和渲染层接受的两个进程正则类型显式登记能力缺口；MATCH/FINAL 由默认去向表达。非默认的专有设置、启用的 overlay/原生 DSL 会产生对应警告；实际输出的原生待验证默认也提示。无关端的命名空间默认值不等于请求该端实现整套原生字段，不批量报无意义告警。blocked、standalone 和本来不同的默认不报共享分叉；当前没有登记为 shared 的设置，因此不设共享分叉代码，以后登记 shared 设置时须同时补上分叉诊断。登记表只列会触发的代码：按端登记的原生组、DNS 和 TUN 记录对其他端是 not_projected。PolicyIR 的 dns、tun、sniffer、rule_providers、http_processing 在 Hub 下发路径上为空，这些段由 Profile 设置在投影时生成，诊断见对应设置项；内部 builder 接口仍接受调用方填值（例如 Surge 会把调用方给的 dns 输出为 dns-server 行），所以这些字段在所属端和不支持的端保留原有代码，非空时报告。生成器校验作用域外的投影必须是 not_projected 且没有代码，代码后缀必须与状态一致。

新告警仅进入管理侧；不会追加设备配置注释，也不会进入下载的 AUDIT.md，确保整包文件仍与基线一致。既有告警注释、blocker 及 PR 75/77 行为完整保留。当前前端没有按 warning code 翻译后端说明的映射，直接展示后端 message，因此本次只给后端中文行为说明，不修改前端或通用 i18n。

## 确定性与下发环境

纯 builder 在固定下发输入下不读随机源、LLM、数据库或本机网络；真实路由传入的签名 URL 回调仍在渲染过程中读取时钟计算 exp，这是基线既有且唯一剩余的渲染时钟输入。本轮保留它，跨时钟只允许 exp 和签名变化；路由级测试冻结时钟核对。旧版 Host 诊断中的本机地址探测移到 `render_environment.capture_local_host_aliases`，由 HTTP 边界捕获，再作为 `local_host_aliases` 传入。观测与期望状态分离；这些别名仍使用原有算法，设备文本的既有 Host 告警保持。

离线包的 `generated_at` 也由管理 HTTP 边界使用原有格式采样后传入；builder 不自行取时间。纯内部调用省略该输入时固定为空，设备 HTTP 交付仍有原有时间戳。需要复现时同时冻结时间戳、URL、revision、设备标识、目标、模式和地址别名；不能把两次实际下载时刻不同的包误当成相同输入。

## 验证与复跑

- 字段/分流覆盖、原生缺失诊断、快照分离和 JSON 往返：`tests/test_configuration_intent.py`。
- 175 个合成样例覆盖全部 family、29 卡片模式、87 key、plain/raw/lazycat、5 个设备 preset、3 种契约策略、3 种动作、DNS/filter 模式、来源/系统/逻辑/远程/重叠规则；含 17 个从既有测试字面量保留的设置样例及既有节点 fixture。两例 nameserver-policy 的 scalar 正例保留，原 list 输入另作负向兼容样例：字节仍对比，内核预期拒绝非法上游值。
- 每个样例重复生成全部文件，验证确定性；纯 builder 渲染禁止环境探测，静态检查不导入 LLM/时钟/随机源；另有经过真实路由的签名时钟测试。
- `scripts/compare_intent_outputs.py --base <git-ref> --candidate WORKTREE --output-dir <new-path>` 从 git archive 导出独立源码，同一合成 corpus 和显式环境/生成时间下逐文件直接比较 bytes。两侧使用不同 PYTHONHASHSEED。不会切换分支或修改其他 worktree。支持 candidate 为另一个 git ref。
- API 层验证 DNS 差异、IP-only/DIRECT 和专有能力告警出现在 preview-summary/render-preview 的结构化诊断，且不产生 409、不进入设备文本。
- 设置 `MIHOMO_BIN` 后运行真实 `mihomo -t` 合成离线包验收；这是内核解析验证，不外推为手机运行或 Surge/Shadowrocket 新实机结果。

## 后续批准边界

统一三端 no-resolve、统一 IPv6/skip-proxy 行为、改变真实地址/Host 映射、实施版本降级/拒绝均会改变设备行为，另列候选并经人批准。本阶段没有新提案、审批、存储迁移、审计身份链或回滚实现；core beliefs #14/#15 的全局能力仍未完成。两路独立 review 及其 fatal/error 收口仍是本任务的后续验收门槛。

## 第 2 轮修正与仍保留的边界

- 整体 DNS/TUN/HTTP 管线均平台特化；strategy_type、IP 解析策略和 rule_type 按取值/平台展开。证据不直接覆盖字段时明确登记缺口，不再把“约束与 lint 视图”当字段证据。
- 三端都读取 clash_udp_default_enabled 写节点 UDP/udp-relay；Mihomo、Surge、Shadowrocket 的运行后果不同，归 blocked。surge_skip_proxy 的 Mihomo 真实绑定为 DIRECT/TUN/fake-ip 适配；clash_tcp_concurrent 不下发。
- IP/DNS 告警按分类与目标聚合，给数量及最多三条示例；overlay 按对象聚合并显示进程名/程序名。用户消息不含内部证据标签，证据和全部跨域代码在登记表。
- 新的真实 Mihomo 用例含用户规则、IP-CIDR、SRC-IP-CIDR 和 rule-provider，显式清空 DNS fallback，且不放 GeoIP 文件，因此可离线解析。完整 corpus 使用本机已有 GeoIP 数据另验，不将无 GEOIP 规则等同于无 GeoIP 依赖。
- 签名时间移到边界、剔除非有限浮点节点、改变 CIDR 参数替换导致的选项丢失，均列为待确认行为变更，本轮不实施。内部快照容许基线已接受的 Infinity/NaN，不能让未知上游额外字段阻断三端输出。

## 第 3 轮性能与可维护性

能力诊断先按规则类型索引；证据缺口按对象汇总，不按登记行重复扫全量规则。没有 IP 策略时不计算身份哈希；需要时派生一次，冻结结构键供投影和 IP 诊断复用，不依赖位置。原始与编译规则相同时共用快照，投影内编译快照只解一次；每次投影仍重建独立对象。既有告警还原仅在相关 warning 存在时建立映射，其依赖的完整英文文案由精确回归固定。

生成器直接拒绝 blocked 规格中的 supported，不再偷偷改状态；UDP 文案进入规格文件。可读性整理前后模型和 round2 测试 AST 相同，生成登记表相同；设备输出另以完整语料和独立 harness 对比。第 3 轮本地验证与独立复核仍是不同证据层。
