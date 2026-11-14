# Troubleshooting

## 本地服务频繁无法访问（127.0.0.1 refused to connect）

请优先查看专项排障文档：

- `docs/operations/local-dev-runbook.md`

该文档记录了本项目近几次高频问题与标准启动方式，包括：

- `.env` 被 `source` 时的 shell 语法坑（如 `APP_NAME` 未加引号）
- `nohup + --reload` 导致的“日志看起来正常但端口未监听”
- 端口冲突/错误 `APP_BASE_URL`/密钥不匹配等场景

## 症状：`Installed` 但 `lzc-cli app log` 返回 `not yet realized`

### 检查顺序

1. 连接状态

```bash
lzc-cli box list
```

2. 容器是否在跑

```bash
lzc-cli docker -- ps -a | grep cloudlazycatsubhub
```

3. Web 容器日志

```bash
lzc-cli docker -- logs cloudlazycatsubhub-web-1 --tail 200
```

4. App 容器日志

```bash
lzc-cli docker -- logs cloudlazycatsubhub-app-1 --tail 200
```

### 常见原因

- 健康检查窗口太短，冷启动被误判
- 外部规则源网络不可达，刷新持续报错
- 路由网关或盒子登录态导致外部访问被重定向
- 启动脚本依赖运行时 `apk add`，而 Alpine mirror TLS/权限异常导致容器在应用启动前退出

### 已采用的缓解策略

- `lzc-manifest.yml` 健康检查改为更宽松窗口（`start_period: 180s`）
- 健康检查改为使用 `python3` 标准库探活，不再依赖额外安装 `curl`
- 构建产物内打包 Linux Python runtime 与离线 wheelhouse，`app/runtime_start.sh` 不再依赖基础镜像自带 Python、运行时 `apk add` 或运行时访问 PyPI
- 可选系统能力必须走降级路径，不能阻塞主服务启动
- 规则拉取失败自动回退本地缓存，不阻断服务

### 如果日志里出现 Alpine mirror 相关错误

常见特征：

- `unexpected eof while reading`
- `Permission denied`
- `no such package`
- `curl: not found`

这类错误优先判定为启动链设计问题，而不是业务代码或上游接口回归。处理方式是移除运行时 `apk add` 依赖，改为只使用基础镜像已提供的 Python 能力完成启动与健康检查。

## 症状：订阅链接访问被重定向到懒猫登录页（HTTP 307）

### 现象

- `GET /sub/clash.yaml?...` 被 307 到 `.../sys/login?...`
- `GET /healthz` 也被 307

### 原因

- `lzc-manifest.yml` 未配置或漏配 `application.public_path`，网关把订阅与探活路径也当作受保护页面。

### 处理

1. 在 `application.public_path` 放行最小集合：
   - `/healthz`
   - `/sub/`
   - `/rules/`
2. 重新构建并安装应用包。
3. 用未登录态复测：
   - `/healthz` 应返回 `200`
   - `/sub/*` 应返回 `200/403`（按 token）
   - `/admin` 仍应 `307` 到登录页

## 症状：Surge 反复弹出 `External Resource` 更新失败窗口

### 现象

- Surge 顶部反复出现 `Resource Update Failed`
- 弹窗里是多条 `DOMAIN-SET` / `RULE-SET`，状态为 `Updating...`
- 事件日志里常见：
  - `Resource Update Failed: Server returned an invalid status code: 403`
  - URL 指向 `/sub/device/.../surge/domain-set/...` 或 `/surge/rule-set/...`
  - 响应体为 `{"detail":"invalid asset signature"}`

### 原因

- Surge 会把远程 `DOMAIN-SET` / `RULE-SET` 当作 external resources 自动刷新。
- 如果客户端仍持有上一版 profile 里的旧资源 URL，而这些 URL 在服务端已经被判定为无效签名，就会持续触发更新失败弹窗。

### 处理

1. 先确认当前资源本身是否已经恢复：

```bash
'/Applications/Surge.app/Contents/Applications/surge-cli' external-resource list
'/Applications/Surge.app/Contents/Applications/surge-cli' external-resource update all
'/Applications/Surge.app/Contents/Applications/surge-cli' dump event | tail -n 50
```

2. 如果当前资源更新成功，但历史事件里仍有旧 revision 的 `403 invalid asset signature`：
   - 优先更新到包含“revision 变化后旧 signed asset URL 仍可通过校验”修复的 SubHub 版本。
   - 然后重新刷新托管 profile；必要时重载一次 Surge profile。

### 判断标准

- 当前 `external-resource update all` 全部返回 `success`
- 新事件里不再持续出现同一批 `/surge/domain-set/*`、`/surge/rule-set/*` 的 `403`
- 弹窗不再周期性自动出现

## 症状：门户打开后没有设备订阅

### 原因

- 账号尚未采集成功
- 设备未识别到有效节点
- 对应设备订阅被禁用

### 处理

1. 后台执行账号采集
2. 检查待申请入口并导入客服域名
3. 在 `/admin/subscriptions` 查看 token 状态

## 症状：标准源拉取提示 `0 valid nodes parsed`

### 现象

- 管理页显示“拉取失败”，错误包含 `0 valid nodes parsed`
- 机场订阅在 Clash/Shadowrocket 客户端可用，但本服务拉取不到有效节点

### 定位顺序（协议诊断）

1. 先看 `pull_result.attempts[*]`：
   - `request_variant`：确认是哪个 UA/格式分支（例如 `ua:clash-verge/2.0`、`format:base64-uri`）
   - `parsed_protocol_counts`：确认是否有协议解析成功计数
   - `skip_reasons`：查看具体跳过原因（如 `unsupported protocol ...`、`invalid ...`）
2. 区分失败类型：
   - 网络失败：`timeout` / `request failed` / `HTTP 4xx/5xx`
   - 格式或协议失败：`0 valid nodes parsed` / `unsupported protocol ...`
3. 常见兼容点：
   - Clash 源：依赖 UA，已内置 `ClashforWindows -> clash-verge -> mihomo` 多 UA 探测
   - Shadowrocket 源：确认返回是 `[Proxy]` INI 还是 Base64 URI（两者都支持）
   - Surge 源：确认 `[Proxy]` 行中协议与参数写法（`anytls/hysteria2/tuic` 支持 `key=value`）
4. 若仍失败：
   - 保存该次 `attempts` 结果（脱敏后）并对照协议字段是否缺失（如 `password/uuid/sni`）
   - 优先用手动拉取接口复现：`POST /api/sources/standard/{source_id}/pull`

## 症状：本地能拉取，懒猫微服拉取失败

### 先别直接查代理桥接

如果你已经确认某条源在本地“关闭代理后”可以成功，第一判断顺序固定如下：

1. 打开本地与懒猫线上两边的标准源编辑页
2. 先看 `拉取链路`
   - 本地若成功配置是 `只走直连`，懒猫线上也必须先改成 `只走直连`
3. 再看 `配置状态`
   - `当前配置指纹`
   - `最近成功配置指纹`
4. 如果两边指纹不同：
   - 先在本地点击“复制配置 JSON”
   - 再到懒猫线上点击“从配置 JSON 导入”
   - 导入后立刻重新拉取验证

### 什么时候才继续查网络

只有满足下面两个条件，才继续排查懒猫盒子的直连出口、IPv4/IPv6 或上游风控：

- 本地与懒猫线上 `pull_network_mode` 已经一致
- 懒猫线上当前配置指纹已经和本地成功配置一致

### 典型案例：FlowerCloud

- 本地成功配置：`direct_only`
- 懒猫线上失败配置：`direct_then_proxy`

这类问题首先是配置漂移，不是代码回归，也不是盒子代理桥接必然失效。

## 症状：`api collection failed: xxx`

### 现象

- 报错中显示 `api collection failed: ...`。
- `/admin/accounts/{id}/crawl` 返回 `400`，快照状态为 `failed`（若未触发 MCP 回退）。

### 原因

- GoRelay API 链路失败（常见为网络不可达、鉴权头不匹配、接口路径配置错误）。
- 系统已改为 API-only，不再执行 DOM/Playwright 兜底。

### 处理

1. 先修 API 链路（优先）：
   - 确认容器到 GoRelay 的 HTTPS 可达。
   - 在懒猫环境使用 IPv4 本地地址 + 系统 CA 的异步 HTTP 客户端配置。
2. 检查 `selectors_json` 兼容迁移告警：
   - 采集结果中的 `source_status.compat_warnings` 若包含 `collector_mode ... migrated`，表示历史模式（如 `api_dom_fallback`/`dom_only`）已被自动迁移到 `api_first`。
3. 若配置了 `mcp_url`：
   - 失败后会尝试 MCP 回退；检查 `source_status.collector` 是否为 `mcp_fallback`。

## 症状：返回 `409/503 setup required`

### 现象

- 当前用户尚未初始化时，管理 API 返回 `409`，管理页面引导到 `/setup`。
- 实例没有已登记用户时，`/sub/*`、`/rules/*` 返回 `503`，`/healthz` 返回 `setup_required=true`。

### 原因

- 当前登录用户还没有工作区。其他用户完成初始化不会自动为当前用户创建工作区。

### 处理

1. 使用懒猫登录态访问 `/setup` 执行初始化。
2. 检查当前用户的 `/api/setup/status`，应为 `initialized=true`、`storage_status=ready`。
3. 旧版根目录数据需要运维显式配置 `LEGACY_DATA_OWNER_ID`；不要通过初始化新用户来接管历史凭据。

## 症状：用户存储返回 `503 user storage unavailable`

### 原因

账号等敏感字段使用持久化的 `field_cipher.key` 加密。数据库缺失、密钥损坏或密钥与密文不匹配会阻止对应工作区加载；其他用户仍可正常使用。

### 处理

1. 保留当前数据库和密钥文件，检查是否发生了卷挂载变更或不完整恢复。
2. 恢复该用户同一份备份中的 `data/subhub.db` 与 `data/field_cipher.key`。新用户工作区位于 `STORAGE_ROOT/tenants/<user-id 的 SHA-256>/`，显式绑定的旧工作区位于 `STORAGE_ROOT/`。
3. 重试管理 API，并确认 `/api/setup/status` 的 `storage_status` 恢复为 `ready`。生成新密钥不能解密旧凭据，策略备份也不代替数据库及原密钥的备份。

## 症状：策略备份同步失败

### 现象

- 管理台“高级 -> 策略备份”显示 `last_result=error`
- `last_error` 包含 `git clone` / `git pull --rebase` / `git push failed`

### 处理

1. 先检查部署配置：
   - `POLICY_BACKUP_REPO_URL`
   - `POLICY_BACKUP_BRANCH`
   - `POLICY_BACKUP_GITHUB_TOKEN`
   - `POLICY_BACKUP_AUTHOR_NAME`
   - `POLICY_BACKUP_AUTHOR_EMAIL`
2. 确认目标仓库是可写的私有仓库，且 token 具备对应 repo 权限。
3. 如果错误发生在 `pull --rebase`：
   - 说明远端分支有新提交且本地镜像无法自动重放
   - 先在 GitHub 上检查是否有人工提交了受管目录（`manifest.json` / `global/` / `categories/` / `scenarios/`）
4. 修复配置后，在管理台点击“立即同步”重试。

## 症状：需要从 GitHub 恢复自有策略

### 处理

1. 进入“高级 -> 策略备份”。
2. 在“恢复来源”里填写分支引用或 commit SHA；留空则使用当前远端分支。
3. 先执行“恢复预览”，确认变更摘要。
4. 再执行“应用恢复”。
5. 恢复后重新检查：
   - 手动分类是否可见
   - 自定义规则是否进入订阅输出
   - 场景 pin groups / catalog bindings 是否恢复

## 症状：置顶分类拖拽无响应

### 现象

- 存在置顶分类或置顶分组时，左侧拖拽手柄无响应
- 无法把分类拖入置顶分组

### 检查顺序

1. 浏览器开发者工具确认拖拽事件：
   - `rulesBody` 是否触发 `dragstart`
   - `event.dataTransfer` 是否包含 `application/x-subhub-category` 或 `text/plain`
2. 检查 drop 区域状态是否残留：
   - `#pinDropZone` 不应长期保留 `.visible` 或 `.drag-over`
   - `.pin-group` 不应长期保留 `.drag-over`
3. 检查前端拖拽状态是否被正确清理：
   - `dragState.categoryName`
   - `dragState.source`
   - `dragState.armedCategoryName`
4. 若仅特定浏览器复现：
   - 清空缓存并硬刷新
   - 对比 `pointerdown -> dragstart -> dragend` 事件链是否完整

### 回归判断

- 无置顶分类时手柄可拖
- 有置顶分组后手柄仍可拖
- chip 在分组间拖拽可用，连续拖拽后状态不残留
