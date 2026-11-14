# SubHub 重构计划（历史归档）

> 历史归档文档。
> 用途：保留项目从 `lzc-lzctoclash` 重构到 `SubHub` 的原始设计背景。
> 不作为当前架构、当前 API、当前交付流程的 authoritative source；当前真相请回到 `AGENTS.md`、`docs/architecture/system-overview.md`、`docs/api/` 和 `docs/governance/`。

## Context

当前项目 `lzc-lzctoclash` 是一个 GoRelay 专用的代理订阅服务，架构复杂（1600 行编排器、域名绑定系统、MCP 回退、多租户、加密存储等）。用户需要将其重构为通用的**订阅聚合服务 SubHub**：聚合 3 个代理订阅源，配合 blackmatrix7 分流规则，按 4 个质量组输出 Clash/Shadowrocket 订阅链接。

核心变化：从"GoRelay 爬虫 + 域名绑定"变成"多源聚合 + 规则路由"。

---

## 架构概览

```
SubHub (FastAPI + SQLite)
│
├─ 订阅源
│   ├─ GoRelay 源 (2个家宽机场) ── GoRelay API 采集 → 按倍率分组
│   │   └─ 每设备不同节点
│   └─ 标准订阅源 (1+个机场) ── 拉取 Clash/SR 订阅 URL → 解析节点
│       └─ 所有设备共享
│
├─ 规则引擎
│   ├─ blackmatrix7 规则目录 (~669个服务分类)
│   ├─ 用户自定义规则
│   └─ 懒猫直连规则 (heiyu.space, lazycat.cloud 等)
│
├─ 输出
│   └─ 每设备: Clash YAML + Shadowrocket .conf
│       └─ 4个代理组 + 内联分流规则
│
└─ 管理
    ├─ Web UI (规则配置 + 源管理 + 设备查看)
    └─ CLI 工具 (AI 友好, JSON 输出)
```

### 4 个质量组

| 组名 | 来源 | 自动分组逻辑 |
|------|------|-------------|
| 高质量-高倍率 | GoRelay 节点, 倍率 >= 3x | `resolve_multiplier()` 提取倍率 |
| 高质量-低倍率 | GoRelay 节点, 倍率 < 3x | 同上 |
| 中等质量 | 标准订阅源 (填入时指定) | 源级别配置 |
| 低质量大流量 | 标准订阅源 (填入时指定) | 源级别配置 |

补充：标准订阅源新增 `高质量机场` 源类型。该类型不会直接作为分组输出，而是按节点名倍率自动拆分：

- `<5x` -> `高质量-低倍率`
- `>=5x` -> `高质量-高倍率`
- 未识别倍率 -> 不纳入任何质量组，并在管理页顶部提示告警

---

## 文件变更清单

### 保留不改
- `app/middleware/lazycat_identity.py` — LazyCat 身份提取
- `app/middleware/observability.py` — Prometheus 指标
- `app/services/collectors/gorelay_api.py` — GoRelay API 采集器
- `app/services/collectors/gorelay_parser.py` — GoRelay 文本解析
- `app/services/device_grouper.py` — 设备名提取
- `app/services/http_client.py` — httpx 客户端
- `app/routes/url_resolver.py` — 基础 URL 解析

### 保留并修改
- `app/services/node_naming.py` — 增加标准源前缀支持
- `app/services/subscription_builder.py` — 从 2 组改为 4 组 + 内联规则 + 懒猫直连
- `app/routes/internal.py` — 改服务名为 subhub, 简化
- `app/services/collectors/__init__.py` — 只导出 GoRelayApiCollector
- `lzc-manifest.yml` — 新名称、子域名、环境变量
- `lzc-build.yml` — 微调
- `requirements.txt` — 可能加 click (CLI)

### 新建
| 文件 | 用途 |
|------|------|
| `app/models.py` | 全新数据模型: GoRelaySource, StandardSource, NodeRecord, ServiceCategory, CustomRule, DeviceSubscription |
| `app/config.py` | 简化配置 (去掉 MCP/Setup/多租户相关) |
| `app/main.py` | 简化启动 (去掉 Setup 守门、MCP) |
| `app/storage/base.py` | 新 Repo 协议 |
| `app/storage/sqlite_repo.py` | 新 SQLite 实现 (新 schema, 无字段加密) |
| `app/services/hub_service.py` | 核心编排器 (~600行, 替代 1600 行 upstream_service) |
| `app/services/rule_catalog.py` | blackmatrix7 规则目录管理 (~300行) |
| `app/services/source_fetcher.py` | 标准订阅 URL 拉取+解析 (~250行) |
| `app/services/normalize.py` | 从 domain_binding_service 提取的纯工具函数 |
| `app/routes/subscription.py` | 订阅输出端点 |
| `app/routes/management.py` | 管理 REST API (Web UI + CLI 共用) |
| `app/routes/ui.py` | V2 SPA 入口路由 (`/manage`) |
| `app/cli/__init__.py` | CLI 包 |
| `app/cli/main.py` | CLI 入口 |
| `app/cli/commands.py` | CLI 命令实现 |

### 删除
- `app/services/upstream_service.py` — 被 hub_service 替代
- `app/services/domain_binding_service.py` — 域名绑定移除 (工具函数提取到 normalize.py)
- `app/services/mcp_client.py` — MCP 回退移除
- `app/services/secret_store.py` — Setup 流程移除
- `app/services/subscription_token_service.py` — 简化内联
- `app/services/extractors.py` — 合并到 source_fetcher
- `app/services/rule_fetcher.py` — 被 rule_catalog 替代
- `app/services/collectors/gorelay_browser.py` — 浏览器采集移除
- `app/security.py` — 自定义加密移除
- `app/tenancy.py` — 多租户移除
- `app/routes/admin.py`, `public.py`, `setup.py` — 被新路由替代
- `app/storage/factory.py`, `migrate.py` — 不再需要
- 经典管理模板与 `app/static/manage/` — 已由 `/manage` 下的 V2 SPA 取代

---

## 数据模型

### SQLite Schema (核心表)

```sql
-- GoRelay 订阅源
CREATE TABLE gorelay_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    login_url TEXT NOT NULL,
    gorelay_username TEXT NOT NULL,
    gorelay_password TEXT NOT NULL,
    proxy_username TEXT NOT NULL DEFAULT '',
    proxy_password TEXT NOT NULL DEFAULT '',
    selectors_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

-- 标准订阅源 (机场)
CREATE TABLE standard_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,          -- 同时作为节点名前缀
    clash_url TEXT NOT NULL,
    shadowrocket_url TEXT NOT NULL,
    login_url TEXT NOT NULL DEFAULT '',
    quality_group TEXT NOT NULL, -- '中等质量' or '低质量大流量' or '高质量机场'
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

-- blackmatrix7 规则分类 (~669条)
CREATE TABLE rule_categories (
    name TEXT PRIMARY KEY,
    assigned_group TEXT NOT NULL DEFAULT '',
    rule_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- 规则内容缓存
CREATE TABLE rule_category_cache (
    name TEXT PRIMARY KEY,
    clash_rules_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

-- 自定义规则
CREATE TABLE custom_rules (
    id TEXT PRIMARY KEY,
    rule_type TEXT NOT NULL,
    value TEXT NOT NULL,
    target_group TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 设备订阅
CREATE TABLE device_subscriptions (
    id TEXT PRIMARY KEY,
    device_key TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT,
    last_seen_ip TEXT
);

-- GoRelay 节点缓存 (每设备)
CREATE TABLE gorelay_node_cache (
    source_id TEXT NOT NULL,
    device_key TEXT NOT NULL,
    nodes_json TEXT NOT NULL,
    device_name TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source_id, device_key)
);

-- 标准源节点缓存
CREATE TABLE standard_node_cache (
    source_id TEXT NOT NULL PRIMARY KEY,
    nodes_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
```

---

## API 设计

### 订阅输出
```
GET /sub/device/{token}/clash.yaml
GET /sub/device/{token}/shadowrocket.conf
```

### 管理 API (Web UI + CLI 共用)
```
# 订阅源管理
GET/POST           /api/sources/gorelay
PUT/DELETE          /api/sources/gorelay/{id}
GET/POST           /api/sources/standard
PUT/DELETE          /api/sources/standard/{id}

# 规则目录
GET                /api/rules/categories?q=search
PUT                /api/rules/categories/{name}
POST               /api/rules/categories/bulk-assign
POST               /api/rules/refresh
GET                /api/rules/export          # LLM 工作流: 导出 JSON
POST               /api/rules/import          # LLM 工作流: 导入 JSON

# 自定义规则
GET/POST           /api/rules/custom
DELETE             /api/rules/custom/{id}

# 设备 & 系统
GET                /api/devices
POST               /api/refresh
GET                /api/status
```

`GET /api/status` 的 `runtime.source_status.standard.{source_id}` 会额外包含：

- `unrecognized_multiplier_count`
- `unrecognized_examples`（最多 5 条）

### Web UI
```
GET /               → 重定向到 /manage
GET /manage         → 管理页面 (单 Jinja2 模板)
```

### CLI
```
subhub sources list / add-gorelay / add-standard / remove
subhub rules list [--q] / assign / bulk-assign / export / import
subhub custom list / add / remove
subhub devices list
subhub refresh / status
```
CLI 通过 HTTP 调用本地 SubHub API, 输出结构化 JSON。

---

## Clash 输出结构

```yaml
mode: rule
allow-lan: false
proxies:
  - {name: "电信·2.3x·广东隧道", type: trojan, ...}     # GoRelay 高倍率
  - {name: "联通·1x·上海隧道", type: trojan, ...}        # GoRelay 低倍率
  - {name: "[机场A] 日本-东京-01", type: ss, ...}         # 标准源, 带前缀
  - {name: "[机场B] 美国-洛杉矶-03", type: vmess, ...}   # 标准源, 带前缀

proxy-groups:
  - {name: "高质量-高倍率", type: select, proxies: [...]}
  - {name: "高质量-低倍率", type: select, proxies: [...]}
  - {name: "中等质量", type: select, proxies: [...]}
  - {name: "低质量大流量", type: select, proxies: [...]}

rules:
  # 懒猫直连 (最高优先级)
  - DOMAIN-SUFFIX,heiyu.space,DIRECT
  - DOMAIN-SUFFIX,lazycat.cloud,DIRECT
  - DOMAIN-SUFFIX,lazycatmicroserver.com,DIRECT
  - IP-CIDR,6.6.6.6/32,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR6,2000::6666/128,DIRECT,no-resolve
  # 自定义规则
  - DOMAIN-SUFFIX,custom.example.com,中等质量
  # blackmatrix7 内联规则 (按分类分配)
  - DOMAIN-SUFFIX,openai.com,高质量-高倍率
  - DOMAIN-SUFFIX,claude.ai,高质量-高倍率
  - DOMAIN-SUFFIX,youtube.com,高质量-低倍率
  - DOMAIN-SUFFIX,t.me,中等质量
  # ...
  - MATCH,DIRECT
```

Shadowrocket .conf 结构类似, 使用 `[Proxy Group]` 和 `[Rule]` 格式。

---

## Web UI 设计

单页面, 4 个标签:

**标签 1: 规则目录** — 搜索框 + 表格 (分类名 | 规则数 | 分组下拉框) + "导出给LLM"按钮 + "从LLM导入"按钮 + 刷新目录按钮 + 已分配计数器

**标签 2: 自定义规则** — 添加表单 + 列表 (删除按钮)

**标签 3: 订阅源** — GoRelay 源管理 + 标准源管理 (名称/前缀、URLs、登录地址跳转链接、质量组)

**标签 4: 设备** — 设备列表 + 每设备的 Clash/SR 订阅链接 (带复制按钮) + 全部刷新

---

## 关键设计决策

1. **规则内联 vs RULE-SET**: 内联所有规则到输出配置中, 客户端无需额外请求
2. **凭据存储**: 去掉自定义 XOR+HMAC 加密, 明文存 SQLite, 依赖容器文件系统隔离
3. **GoRelay pending_domain 节点**: 仅包含 status="ready" 的节点, 跳过未解析域名的
4. **blackmatrix7 目录获取**: GitHub API `/git/trees/master?recursive=1` 获取分类列表 + raw.githubusercontent.com 获取规则内容, 每日刷新
5. **normalize 工具函数**: 从被删除的 domain_binding_service.py 提取到新的 `app/services/normalize.py`

---

## 实现顺序

### Phase 1: 基础 (模型 + 存储 + 配置)
- 重写 `models.py`, `config.py`, `storage/`
- 创建 `normalize.py` (提取工具函数)
- 简化 `main.py` 启动流程

### Phase 2: GoRelay 通路 (最小可用)
- 创建 `hub_service.py` (先只支持 GoRelay)
- 改造 `subscription_builder.py` (4 组结构)
- 创建 `subscription.py` 路由
- **checkpoint**: GoRelay 设备能拉取到 4 组 Clash 配置

### Phase 3: 规则引擎
- 创建 `rule_catalog.py` (blackmatrix7 集成)
- 完善 subscription_builder 的规则内联
- **checkpoint**: 输出包含完整分流规则

### Phase 4: 标准订阅源
- 创建 `source_fetcher.py` (解析 Clash/SR 订阅)
- hub_service 集成标准源
- 修改 `node_naming.py` 支持前缀
- **checkpoint**: 3 个源全部聚合输出

### Phase 5: 管理接口
- 创建 `management.py` (REST API)
- 创建 `/manage` V2 SPA (Web UI)
- 创建 `cli/` (CLI 工具)

### Phase 6: 清理 + 部署
- 删除所有废弃文件
- 更新 `lzc-manifest.yml` / `lzc-build.yml`
- 测试完整流程
- 更新文档

---

## 验证方法

1. **GoRelay 采集**: 启动后调用 `/api/refresh`, 检查 GoRelay 节点按倍率正确分组
2. **标准源解析**: 添加一个标准源, 验证节点带正确前缀并归入指定质量组
3. **规则目录**: 调用 `/api/rules/categories` 确认加载 ~669 个分类, 搜索 "OpenAI" 能找到
4. **规则分配**: 分配几个分类到不同组, 拉取订阅链接验证规则正确内联
5. **LLM 工作流**: 导出 JSON → 手动修改 → 导入, 验证分配更新
6. **多设备**: 不同 token 拉取的配置中 GoRelay 节点不同, 标准源节点相同
7. **懒猫直连**: 验证输出配置中 heiyu.space 等规则在最前面
8. **CLI**: `subhub rules list --q AI` 返回 JSON 格式的 AI 相关分类
9. **Web UI**: 浏览器访问 /manage, 能搜索分类、切换分组、管理源
