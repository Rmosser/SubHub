# SubHub Golden Principles

> 本文列出实现判定，状态以各条落点为准；不得把目标当作已实现能力。
> 产品配置原则以 [core beliefs](design-docs/core-beliefs.md) 为唯一权威；本文只给出对应实现约束。
> 新增或修改涉及这些领域的代码时，必须遵守以下判定。

## GP-01: 按能力域定锚，跨端逐层投影

跨端取舍遵循 [core belief #0](design-docs/core-beliefs.md#0-元原则按能力域定锚跨端逐层投影)。

**MUST**: 客户端能力分叉集中在共享层（如 `_contract_members()`、`_business_group_members()`），不在各端渲染器中分散判定
**MUST**: family 的支持结论有对应能力矩阵和验证证据，不以 UI 顺序代替证据
**FORBIDDEN**: 用固定品牌顺序决定能力上限，或把仅报 warning 当成已批准降级

- 原因：能力判断集中，三端才不会各自定义同一意图
- 当前落点：共享成员选择、Profile 能力矩阵、协议支持检查；统一降级批准尚未实现
- 关联 core belief：#0；批准约束见 #14

## GP-02: 质量梯队隔离——不得跨梯队降级

**核心不变量**：每个质量梯队的策略组成员只包含本梯队节点 + REJECT 兜底。
当本梯队节点全部失败时，流量终止于 REJECT，不得自动切换到其他梯队。

**MUST**: 策略组成员仅由 `_pool_mode_names()` 对应梯队的节点构成，终端 fallback 为 REJECT
**MUST**: 四个梯队（高质量·高倍率 / 高质量·低倍率 / 中质量 / 低质量）各自独立，互不借节点
**MUST**: 高质量节点的出口只能是 GoRelay 提供的高质量中继站（出口 IP 和端口从 GoRelay API 抓取，凭据显式提供）。链式家宽通过中/低质量家宽作为入口、GoRelay 高质量节点作为出口的方式运行，因此可以出现在高质量 contract 的 fallback 链中——判定梯队归属看出口质量，不看入口质量
**FORBIDDEN**: 高质量组中出现中质量或低质量节点名（指出口本身为中/低质量的节点）
**FORBIDDEN**: 以"高质量全挂了用户总得能上网"为由跨梯队自动降级

- 原因：用户在 Surge Policy 页面看到的策略组成员必须严格对应梯队出口质量，宁可 REJECT 中断也不让用户误以为在用高质量线路
- 代码位置：`app/services/subscription_builder.py` 的 `_pool_mode_names()`、`_with_chain_proxy()`（链式代理包装）；`app/services/hub_service.py` 的 `_build_chain_home_combo_nodes()`、`_with_chain_home_combinations()`（链式组合节点构建）
- 关联 core belief：#2（节点质量分层治理是本项目存在的前提）、#5（系统永远不隐瞒问题）

## GP-03: 策略组合标准化——统一子组命名

**MUST**: 每个策略池（quality group）通过 `_pool_mode_names()` 生成子组，当前为单子组：`·自动`
**MUST**: 链式入口同样通过常量定义：`链式入口·自动`
**MUST**: business group 和 contract 通过 mode_key 选择子组，不直接构造组名

**MUST**: business group 的 `pool_names` 必须显式声明路由池；未知或缺失
pool contract 时 fail closed 到 `REJECT`，不得从 group name 推断 medium 等池。
**FORBIDDEN**: 跨策略池共享子组（每个池的子组独立命名）
**FORBIDDEN**: 硬编码子组名（如 `f"{pool}·自动"`）绕过 `_pool_mode_names()`

- 原因：配置文件结构可预测、可调试、可自动生成；子组命名一致让用户在客户端中快速定位
- 代码位置：`app/services/subscription_builder.py` 的 `_pool_mode_names()`、`_CHAIN_INGRESS_GROUP_NAME`（链式入口子组常量）
- 关联 core belief：#3（用户对自己的配置拥有完全的可见性和控制权）、#4（所有分类必须显式声明）

## GP-04: GEOIP/IP-ASN 仅身份碰撞——去重限定同身份范围

**MUST**: 节点去重的 materialization key 包含 `device_key`、`entry_name`、`isp`、`ip_version`、`host:port`
**MUST**: 只有当所有身份维度完全相同时才视为重复
**MUST**: ISP 通过 `resolve_gorelay_isp()` 标准化后再参与去重
**FORBIDDEN**: 跨设备去重（不同 device_key 的相同节点各自保留）
**FORBIDDEN**: 跨 ISP 去重（不同运营商的相同 IP 可能语义不同）
**FORBIDDEN**: 跨 IP 版本去重（IPv4 和 IPv6 的相同入口名各自保留）

- 原因：碰撞范围最小化，避免误删有效节点。不同运营商/IP 版本的同名入口可能路由路径完全不同
- 代码位置：`app/services/gorelay_service.py` 的 `_node_materialization_key()`（定义）与 `_materialize_nodes()`（去重使用处）；`app/services/normalize.py` 的 `resolve_gorelay_isp()`
- 关联 core belief：#1（边界处翻译与守门，内部只说一种语言）、#4（分流语义必须显式声明，系统不做推断）

## GP-05: 外部输入先校验，节点统一为 NodeRecord

边界规则见 [core belief #1](design-docs/core-beliefs.md#1-边界处翻译与守门内部只说一种语言)；配置提案不属于 `NodeRecord`，须走各自的配置 schema。

**MUST**: 订阅源节点、配置文件和远程规则列表使用各自的入口校验器，拒绝不合法输入
**MUST**: 外部节点数据经 SourceFetcher / GoRelayService 转换为 `NodeRecord` 后才进入内部流程
**MUST**: 协议特有字段保存在 `NodeRecord.raw` 中，核心字段（name, host, port, protocol）统一提取
**FORBIDDEN**: 内部模块直接处理外部格式的 raw dict（如 Clash proxy dict、Surge INI 段）
**FORBIDDEN**: 内部模块对已校验数据写防御性 if-else（如 `if node.host is None`）

- 原因：边界处一次性完成翻译和守门，内部代码只需信任一种数据形状，消除格式分散带来的复杂度
- 状态：节点转换已有实现；配置提案的完整门控状态见 #1
- 代码位置：`app/models.py` 的 `NodeRecord`；`app/services/source_fetcher.py` 的 `_parse_clash_payload()`、`_node_from_clash_proxy_with_reason()`（Clash → NodeRecord）；`app/services/gorelay_service.py` 的 `_materialize_nodes()`、`_materialize_chain_home_nodes()`（GoRelay → NodeRecord）
- 关联 core belief：#1（边界处翻译与守门，内部只说一种语言）

## GP-08: 规则冲突以确定性 rank 裁决——system 源优先于 custom

当两条规则共享同一 identity `(rule_type, normalized_value, extras)` 但指向不同 contract 时，
通过确定性 5-tuple rank 裁决胜负。关键违反直觉之处：system 源优先于 custom 源。

**MUST**: 规则 identity 冲突时，按 5-tuple rank 裁决，排名小者保留：
  (1) plane：目标契约的 `routing_action` 为 reject (0) > 其余 (1)
  (2) source_kind: system (0) > custom (1) > catalog (2)
  (3) target：reject 动作固定 -1，direct 动作固定 4，代理契约取自己的 `sort_order`；显式契约目录里找不到的目标为 99。没有契约目录的兼容路径按预置 ID 判定（AD_BLOCK / REJECT 为 -1，HQ_PREMIUM 0 … BULK 3，DIRECT 4）
  (4) rule_family: domain (0) > misc (1) > ip (2)
  (5) first_seen_index
**MUST**: 输家规则产生 `conflicting-rule-target` 警告，包含 kept/dropped 的 display name 和 source_kind
**FORBIDDEN**: 使用 last-writer-wins 或 first-writer-wins
**FORBIDDEN**: 保留两条冲突规则让客户端自行去重
**FORBIDDEN**: source_kind 排序中 custom 优先于 system（system 保护梯队隔离）

- 原因：system 源代表质量梯队的核心路由意图，custom 是用户个性化调整。system 优先防止用户误操作破坏梯队隔离
- 代码位置：`app/services/subscription_builder.py` 的 `_POLICY_RULE_SOURCE_ORDER`、`_POLICY_RULE_TARGET_ORDER`、`_policy_rule_plane_rank()` / `_policy_rule_source_rank()` / `_policy_rule_target_rank()` / `_policy_rule_family_rank()` / `_policy_rule_conflict_rank()`（rank 定义）与 `merge_policy_rule_entries()`
- 关联 core belief：#0（按能力域定锚，跨端逐层投影）、#2（节点质量分层）、#5（系统永远不隐瞒问题）

## GP-09: 跨客户端语义翻译在 IR 富化阶段执行

本条限定现有字段的适配位置；共享边界服从 core belief #0 与 GP-16，不要求统一意图沿用某端的输入语法。

客户端特有概念（如 Surge skip-proxy）存储时保持源客户端原生格式。
当需要渲染为另一客户端（如 Mihomo）时，语义翻译在 IR 富化阶段执行，
既不更早（存储层不知道目标客户端），也不更晚（渲染层不应做结构变换）。

**MUST**: 客户端特有概念以源客户端原生格式存储
**MUST**: 跨客户端语义翻译在 `_enrich_policy_ir_for_target()` 中执行，分解为目标客户端原生字段
**MUST**: skip-proxy 分解始终产出 Mihomo 的 DIRECT 规则与 `tun.route-exclude-address`；仅在目标配置启用 `fake-ip` 模式时额外产出 `dns.fake-ip-filter`
**FORBIDDEN**: 按客户端预存分解后的字段（存储层不知道目标客户端）
**FORBIDDEN**: 在渲染阶段（文本输出层）执行语义翻译或结构变换

- 原因：存储层不知道目标客户端，渲染层的职责是 IR→文本。IR 富化层是唯一同时知道"源意图"和"目标能力"的位置
- 代码位置：`app/services/skip_proxy_decomposer.py` 的 `decompose_skip_proxy()`（分解器）；调用处在 `app/services/subscription_builder.py` 的 `_enrich_policy_ir_for_target()`
- 关联 core belief：#1（边界处翻译，内部只说一种语言）、#0（按能力域定锚，跨端逐层投影）

## GP-10: 共享 base IR + copy-on-enrich——禁止原地变异

`build_policy_ir()` 构建的 base IR 可能被多设备/多客户端并发引用。
渲染前必须通过浅拷贝创建副本，客户端特有的富化操作只在副本上执行。

**MUST**: `build_policy_ir()` 构建共享 base IR，渲染前通过 `_copy_policy_ir()` 创建浅拷贝副本
**MUST**: 客户端特有的富化操作（DNS、TUN、skip-proxy 分解等）只在副本上执行
**FORBIDDEN**: 直接修改共享 base IR（并发请求时会导致客户端设置交叉污染）
**FORBIDDEN**: 为每个客户端从头重建完整 IR（丢失 base IR 缓存优势）

- 原因：多设备/多客户端可能并发请求配置，共享 base IR + 浅拷贝是正确性与性能的刻意权衡
- 代码位置：`app/services/subscription_builder.py` 的 `_copy_policy_ir()` 与 `_enrich_policy_ir_for_target()`
- 关联 core belief：#3（用户对配置拥有完全可见性）、#1（内部只说一种语言）

## GP-11: Business group 渲染顺序以质量梯队为主键

配置文件中 business group 的渲染顺序以硬编码质量梯队优先级为主键，
用户的 sort_order 仅在同梯队内作为次要排序键。

**MUST**: business group 渲染排序以硬编码质量梯队优先级 `_ENTRY_GROUP_ORDER` 为主键
  （HIGH_PREMIUM=0, HIGH_STANDARD=1, MEDIUM=2, BULK=3, CHAIN_HOME=4, Default=5, DIRECT=6, AD_BLOCK=7）
**MUST**: 用户 `sort_order` 仅作为同梯队内的次要排序键
**FORBIDDEN**: 以用户 sort_order 为主键排序 business group（会导致低质量出口在客户端中被优先选中）

- 原因：渲染顺序影响客户端策略组列表的展示和自动选择行为，必须保证高质量组排在前面
- 代码位置：`app/services/subscription_builder.py` 的 `_ENTRY_GROUP_ORDER`、`_business_group_sort_key()`、`_ordered_business_groups()`
- 关联 core belief：#0（按能力域定锚，跨端逐层投影）、#2（节点质量分层是项目存在的前提）

## GP-12: 分组只管理，分类决定去向——禁止用分组推导规则目标

`catalog_group` / `pin_group` 这类分组字段只表达管理视图中的归类与展示顺序，
不表达分类命中后的流量去向。分类的 route/contract 必须单独声明，且是规则目标的唯一来源。

**MUST**: 分类的路由去向由分类级 route/contract 单独声明
**MUST**: 分类自定义规则、LLM 产出的分类规则、后续同类能力都继承分类自己的 route/contract
**MUST**: 同一展示分组内的分类允许指向不同 contract
**FORBIDDEN**: 用 `catalog_group`、`pin_group`、`assigned_group`、`effective_group` 这类展示或历史字段推导规则目标
**FORBIDDEN**: 让规则因“当前所在分组”自动改写去向
**FORBIDDEN**: 把“同组其他分类的当前生效去向”当成当前分类规则的上下文

- 原因：分组是给人看的目录结构，不是给系统做路由决策的 authority。把管理分组和流量去向混在一起会导致设计漂移，并制造隐藏耦合
- 口语化例子：`1337x` 被摆在某个分组里只影响管理展示；`1337x` 的规则命中后仍走 `1337x` 自己绑定的 contract，而不是该分组的默认去向
- 保留的例外：`app/models.py` 的 `effective_contract_id()` 在分类所在分组为 ad-block 模式时直接返回 REJECT，`app/routes/management.py` 的 `_effective_contract_payload()` 把它用于分类自定义规则。人已确认保留，不按漂移修；其他分组模式仍不得决定去向。前端 `CategoryCustomRulesPanel.tsx` 不读分组字段
- 关联 core belief：#4（分流语义必须显式声明，系统不做推断）、#6（分组只管理视图，分类决定流量去向）

## GP-13: 生效中的契约语义必须有单一权威来源

契约是 [core belief #0](design-docs/core-beliefs.md#0-元原则按能力域定锚跨端逐层投影) 在路由域的现有落点；配置分工和批准约束分别见 core beliefs #3、#14。

**MUST**: 系统中所有面向用户和工作流暴露的契约语义，必须来自同一份显式配置
**MUST**: 管理台展示、规则分配、LLM 工作流、默认去向使用同一套契约定义
**FORBIDDEN**: 在不同模块各自维护一套 contract 名称、说明和目标语义
**FORBIDDEN**: 直接把代码常量当作最终用户语义
**MUST**: 每个持久化契约显式声明 `routing_action=proxy|direct|reject`；渲染、可绑定能力按动作和拓扑判定，不按预置 ID 判定
**MUST**: 所有契约都允许按 owner scope 编辑和删除；被引用/用作默认时先明确迁移，空草稿不生成订阅
**FORBIDDEN**: 启动、升级或恢复后因缺少预置 ID 自动补回用户删除的契约

- 原因：契约语义一旦分裂，改名、合并、迁移都会出现假同步
- 代码位置：`app/models.py` 的契约动作与能力、`app/storage/sqlite_repo.py` 的定义与一次性初始化、`app/routes/management.py` 的生命周期与引用迁移、`app/services/subscription_builder.py` 的三端渲染；工作流通过 `route_contract_views.py` 读取当前定义；引用迁移由 `app/routes/management.py` 的 `_contract_references()`、`_replace_contract_references()` 执行，`tests/test_contract_lifecycle_api.py` 验证
- 关联 core belief：#3（用户对生效中的路由语义拥有完全的可见性和控制权）、#4（分流语义必须显式声明，系统不做推断）

## GP-16: 可统一意图的跨端能力必须单一真相

意图与四层差异的判定以 [core belief #0](design-docs/core-beliefs.md#0-元原则按能力域定锚跨端逐层投影) 为准，family 证据见 [Profile 审计](design-docs/profile-single-source-review.md)。

**MUST**: 已确认 shared / adapted 的 family 保存路径回写同一来源，镜像 key 不得独立漂移
**MUST**: blocked 在证据补齐前保持待验证，standalone 保留明确的单端边界
**FORBIDDEN**: 把相同输入语法当成共享前提，或因字段名相似强行合并
**FORBIDDEN**: 让客户端视角形成第二份可独立编辑的意图

- 原因：保存路径必须服从领域判定，不能反由历史 key 决定共享边界
- 当前落点：`excluded-routes`、`ipv6-policy`、`control-api-access`、`skip-proxy` 的共享保存；统一意图模型尚未实现
- 代码位置：`app/services/profile_capabilities.py`、`app/services/profile_editor_schema.py`、`app/routes/management.py`
- 关联 core belief：#0、#1、#3；确定性输出见 #16

## 维护规则

- 新增 GP 时：同时补代码位置和关联 core belief；编号固定，删除的编号不复用
- 只复述 core belief、删掉也不改变实现决定的条目不进本文件
- 代码位置写文件和符号名，不写行号；GP 对应的代码被重构或改名时，必须同步更新本文件的代码位置
- 发现代码中有未文档化的架构决策时：评估是否应提升为新 GP
- 每条 GP 的 MUST/FORBIDDEN 必须是二值判定，不用 "prefer" 或 "consider"
