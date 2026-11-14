# System Overview

## 目标

把 GoRelay / 标准源采集、规则归类和设备级订阅发布自动化，稳定输出 Clash / Shadowrocket / Surge 订阅，以及管理端审核包。

## 当前模块边界

### Routes

- `app/routes/subscription.py`
  - 匿名订阅接口
  - Clash provider / Shadowrocket nodes / Surge 资产下载
- `app/routes/management.py`
  - 管理 API
  - 设备预览、审核包导出、规则与合同配置
- `app/routes/gorelay.py`
  - GoRelay 兼容/调试入口
- `app/routes/internal.py`
  - 健康检查与内部状态
- `app/routes/ui.py`
  - 门户页、管理页面、setup 页面

### Services

- `app/services/tenant_registry.py`
  - 持久登记已初始化的 LazyCat 用户
  - 为每个用户创建独立 Settings、SQLite、字段密钥和服务实例
  - 公开订阅按已登记 token / public ID 解析所属用户；管理请求始终按登录用户选择服务
  - 启动与关闭覆盖所有已登记用户的后台采集和策略备份

- `app/services/hub_service.py`
  - 采集编排
  - 设备订阅视图构建
  - token 对应节点/规则聚合
- `app/services/gorelay_service.py`
  - GoRelay 账号采集与快照管理
- `app/services/source_fetcher.py`
  - 标准源拉取与协议解析
- `app/services/rule_catalog.py`
  - 规则分类、锁定、directness review
- `app/services/subscription_builder.py`
  - `policy_ir`
  - Clash / Shadowrocket / Surge 渲染
  - blocker / warning 诊断
- `app/services/review_bundle.py`
  - Surge reviewer bundle 审计和导出
- `app/services/lazycat_profile.py`
  - LazyCat 默认 profile 配置
- `app/services/egress_diagnostics.py`
  - 懒猫容器出站诊断

### Frontend

- `frontend/`
  - React 18 + TypeScript + Vite，Cloudscape 3 提供表单控件、下拉按钮、modal 与 table
  - 构建产物输出到 `frontend/vite.config.ts` 的 `outDir`（不入库），由 `app/routes/ui.py` 挂在 `/manage`（Vite `base: "/manage/"`）
  - 只调用管理 API，不自带语义；开发时 Vite 把 `/api`、`/sub`、`/static` 代理到本地后端
- `frontend/src/glass/`、`frontend/src/styles/glass.css`
  - 玻璃工作台外壳：床面、导航沙洲和玻璃材质；视觉与交互约定见 [DESIGN.md](../../DESIGN.md)
- `frontend/src/pages/`
  - 每个管理页一个目录；Profile 页（配置与场景）是只读读图

### Storage

- `app/storage/sqlite_repo.py`
  - SQLite 持久化
  - runtime settings / sources / subscriptions / snapshots
- `app/storage/base.py`
  - 存储抽象接口

## 关键数据流

1. 管理端配置 GoRelay 源或标准源。
2. `hub_service` 调用采集服务刷新节点和规则缓存。
3. `rule_catalog`、合同配置和设备策略共同生成 `policy_ir`。
4. `subscription_builder` 把 `policy_ir` 渲染成三种客户端订阅，或导出 Clash / Surge 审核产物。
5. 客户端通过 token 拉取订阅；管理端通过受保护接口导出离线审核包。

## 可靠性策略

- 用户隔离：生产 `MANAGE_API_REQUIRE_LOGIN=true` 时，每个用户使用
  `STORAGE_ROOT/tenants/<sha256-user-id>/`，数据库、缓存、二维码资产、工作流、字段密钥和备份工作目录均隔离。
  新用户通过 `/api/setup/init` 持久登记；普通访问和未知公开 token 不创建用户空间。
- 旧数据归属：根目录原有数据仅在部署显式配置 `LEGACY_DATA_OWNER_ID` 时归属该用户，
  保留原数据库、密钥与备份路径。首次登录和用户角色不能认领旧数据；已登记归属不能通过改配置转移。
- 本地模式：`MANAGE_API_REQUIRE_LOGIN=false` 明确运行单用户共享空间；身份 header 不形成隔离边界。
- 公开健康检查：`/healthz` 只返回实例健康、初始化状态与访问模式；用户采集、来源和出站诊断由认证接口返回。

- 账号/源级隔离：单个上游失败不阻断其他源。
- 设备级 blocker：被引用的空合同不会继续下发高风险 Clash / Surge 配置。
- 规则缓存回退：外部规则源失败时优先保留最近可用缓存。
- 文档与测试并行维护：订阅输出契约以 `docs/api/subscription-output-contract.md` 为准。

## 契约生命周期

- 节点质量池是资源边界；路由契约是用户拥有的策略定义，两者身份独立。
- `routing_action` 显式表达 `proxy`、`direct` 或 `reject`，不通过契约 ID、名称或池成员猜测。
- 初始七项模板只播种一次。旧库迁移保留 ID、名称、拓扑、场景视图和引用，解除永久系统保护。
- 全局契约由默认场景管理拓扑和删除；场景契约由 owner 管理，继承视图继续遵守作用域。
- 删除时引用和默认去向必须由用户指定替代项，替换与删除在同一 SQLite 事务中完成。
- 允许没有契约/默认项的草稿；生成订阅前验证有效默认项及全部引用，缺失时返回可见阻断。
- `action-direct` / `action-reject` 是显式直连审核/拦截产生的底层目标，不是契约目录记录。
- 策略备份 v2 保存完整目录，恢复同时应用新增、变更和删除；v1 仅在显式恢复时做模板兼容。
