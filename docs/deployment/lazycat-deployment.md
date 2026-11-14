# LazyCat Deployment Guide

## 1. 前置检查

```bash
lzc-cli --version
lzc-cli box list
```

确保 `box list` 返回 `READY`。

## 2. 构建与安装

LPK 携带运行与运维文档，但不包含 docs 下的 `参考项目/` 目录。该目录只在本地存在（已被 git 忽略），仅供设计参考，
其中的第三方源码、Git 历史和依赖缓存由 `scripts/stage_package_docs.py` 在组装时排除；
清理或重新生成安装包不修改本地参考项目。

`requirements.txt` 是 LPK 的完整运行时依赖契约。二维码解码直接声明
Pillow 与 `zxing-cpp`；由于上游没有 CPython 3.13 musllinux wheel，仓库
在 `vendor/wheels/` 固定并校验对应 wheel，构建脚本把它和 PyPI 下载的
其余 musllinux wheels 一起打入离线安装目录。不要删除本地 wheel 后仅在
macOS 环境验证构建。

当前生产服务基于固定 digest 的 `registry.lazycat.cloud/alpine:3.21`
运行时镜像。1.0.10 的 `sha256:fa7042902b0e812e73bbee26a6918a6138ccf6d7ecf1746e1488c0bd76cf1f34`
已在开发机按 `linux/amd64` 实际拉取并回读 `RepoDigests` 与架构；固定 digest 再次拉取成功。
升级时必须在目标盒子验证仓库中确实存在该 digest，不能直接套用其他仓库的同名镜像 digest；
镜像的 config ID 也不能作为 manifest digest 使用。

在已批准的目标盒子上检查固定镜像（引用必须与 `lzc-manifest.yml` 一致）：

```bash
lzc-docker pull --platform linux/amd64 registry.lazycat.cloud/alpine:3.21@sha256:fa7042902b0e812e73bbee26a6918a6138ccf6d7ecf1746e1488c0bd76cf1f34
lzc-docker image inspect registry.lazycat.cloud/alpine:3.21@sha256:fa7042902b0e812e73bbee26a6918a6138ccf6d7ecf1746e1488c0bd76cf1f34 --format '{{.Os}}/{{.Architecture}} {{json .RepoDigests}}'
```

回读应为 `linux/amd64`，且 `RepoDigests` 包含以上固定 digest。LPK 构建成功无法替代此检查。

```bash
lzc-cli project build
lzc-cli app install .pkgout/*.lpk --apk n
lzc-cli app status cloud.lazycat.subhub
```

`lzc-cli project build` 先用当前源码执行 `npm run build --prefix frontend`，重建未入库的管理端构建产物再打包，避免把旧检出构建的管理端打进 LPK；构建前需要已执行 `npm ci --prefix frontend`（Node 版本见 `.nvmrc`），没装前端依赖时构建直接失败。

仅构建（不会切换盒子或安装）：

```bash
bash scripts/deploy_to_lazycat.sh
```

真实安装必须显式指定批准盒子并确认：

```bash
bash scripts/deploy_to_lazycat.sh --deploy --box <box-name> --confirm
```

安装后脚本先读回安装状态与版本，再等新容器起来：`app install` 返回时 release 容器往往还在重建，这时 `project exec` 报 `Service "web" is not running`。脚本每 5 秒重读一次容器内的内容 digest 与 `/healthz`，两项都通过才打印 `verified <package> <version> on <box>`；最多等 180 秒（`DEPLOY_READBACK_TIMEOUT_SECONDS`、`DEPLOY_READBACK_INTERVAL_SECONDS` 可调，整数秒）。超时或任何一步失败都打印 `[deploy_to_lazycat] ERROR:` 并以非零退出，默认盒子照常切回。没有 `verified` 这一行就不算部署完成。

部署前确认 `lzc-manifest.yml` 已放行：

- `/healthz`
- `/sub/`
- `/rules/`

## 3. 配置与初始化

### 3.1 Manifest 环境变量

- `APP_NAME=SubHub`
- `APP_BASE_URL=`：默认留空，优先使用 `LAZYCAT_APP_DOMAIN`
- `STORAGE_ROOT=/lzcapp/var`
- `REFRESH_INTERVAL_MINUTES=30`
- `REQUEST_TIMEOUT_SECONDS=20`
- `VERIFY_TLS=true`
- `RULE_CATALOG_REFRESH_HOURS=24`
- `MANAGE_API_REQUIRE_LOGIN=true`
- `LEGACY_DATA_OWNER_ID`：由可选部署参数 `legacy_data_owner_id`（`lzc_uid`）映射；升级时明确指定根目录旧数据的唯一 LazyCat 用户，缺省为空
- `POLICY_BACKUP_ENABLED=false`（默认关闭；只有受控运行时 Secret 与审核后的目标绑定
  均已配置时才允许显式开启）
- `POLICY_BACKUP_REPO_URL=https://github.com/<owner>/<backup-repo>.git`
- `POLICY_BACKUP_BRANCH=main`
- `POLICY_BACKUP_GITHUB_TOKEN`：由 `lzc-deploy-params.yml` 的 `secret` 参数在安装时注入；
  默认 `POLICY_BACKUP_ENABLED=false`，未配置完整备份契约时不得开启
- `POLICY_BACKUP_AUTHOR_NAME=<author-name>`
- `POLICY_BACKUP_AUTHOR_EMAIL=<author-email>`
- `POLICY_BACKUP_SUBDIR=`
- `POLICY_BACKUP_DEBOUNCE_SECONDS=5`
- `RUNTIME_HEARTBEAT_INTERVAL_SECONDS=30`：resident worker 写入 heartbeat 的最大间隔
- `RUNTIME_HEARTBEAT_STALE_SECONDS=90`：required worker 超过此时长没有 heartbeat 时，`/readyz` 返回 `503`；必须严格大于 heartbeat interval，否则服务拒绝启动
- `RUNTIME_ALERT_WEBHOOK_URL`：由 `lzc-deploy-params.yml` 的 secret 参数注入；必须是不含内嵌凭据的 `https://` JSON 告警接收端；未配置时 `/readyz` fail-closed
- `RUNTIME_ALERT_TIMEOUT_SECONDS=5`：HTTPS 告警投递超时（1--60 秒）
- 启动只在固定全局预算内重试有限数量的 durable 告警 receipt；预算外的 `pending/unknown` obligation 由 resident watchdog 后续以同一 `Idempotency-Key` 重试，不阻塞服务监听

规则：

- 分发包与仓库都不包含真实 token / key；GitHub token 只能通过部署时的 secret 参数注入
- `POLICY_BACKUP_ENABLED=true` 时，HTTPS 备份仓库、token、作者姓名和作者邮箱必须完整，否则服务拒绝启动
- 用户级订阅 token 存在持久化存储中，不依赖 manifest 明文
- GoRelay 采集走环境代理；标准源采集按 `pull_network_mode + trust_env` 控制

`lzc-deploy-params.yml` 声明两个可选参数；manifest 通过
`{{ default "" .U.legacy_data_owner_id }}` 与
`{{ default "" .U.policy_backup_github_token }}` 映射到 `web` 环境变量。
缺省值为空，分发包只携带参数声明与模板，不保存实例用户 ID 或真实 GitHub token。
平台在安装或重新配置实例时收集参数并持久化；全部参数可选时可能跳过安装参数界面，
升级旧数据前应进入实例部署配置设置已核实的归属。`lzc-cli 2.0.9 lpk install` 没有参数注入选项。
参数与渲染契约见 [部署参数规范](https://developer.lazycat.cloud/spec/deploy-params.html)
和 [manifest 渲染规范](https://developer.lazycat.cloud/advanced-manifest-render.html)。

### 用户空间与升级归属

生产登录模式为每个用户保存独立的
`STORAGE_ROOT/tenants/<sha256-user-id>/data/subhub.db` 与 `field_cipher.key`。
注册记录保存在 `STORAGE_ROOT/data/tenant_registry.db`；重启后公开订阅仍可按设备 token / public ID
找到原所属用户。首次访问 `/setup` 并初始化只创建当前用户的空空间和默认设备，不认领旧配置。

升级旧实例时，运维人员必须在修改升级配置前核实旧数据所属的 LazyCat 用户 ID，再配置 `LEGACY_DATA_OWNER_ID`；不得根据首次登录用户或 owner 角色猜测。
该用户原地使用根目录旧数据库、字段密钥、设备 token 和备份路径；其他用户仍使用独立空空间。
服务保留原数据，不复制、不删除，也不根据首次登录或 owner 角色猜测归属。
已经登记的旧数据归属不能通过改为另一个用户 ID 转移。

新用户的策略备份在 `POLICY_BACKUP_SUBDIR/tenants/<sha256-user-id>/` 下维护，避免覆盖其他用户的文件。
新用户未配置 `URL_SIGNING_SECRET` 时从该用户持久随机字段密钥派生签名密钥；
旧根目录和本地共享模式继续沿用原签名设置，保持已发出的资产链接兼容。
`MANAGE_API_REQUIRE_LOGIN=false` 是本地单用户共享模式，不能用身份 header 声称多用户隔离。

公开 `/healthz` 只展示实例状态；详细采集与出站诊断请登录后读取 `/api/status` 或 `/diagnostics`。

### 3.2 懒猫双路出站

- GoRelay 采集：显式使用环境代理
- 标准源采集：按 `pull_network_mode` 在 `direct` / `proxy` 间切换
- 若某条标准源只在本地直连成功，优先把该源设为 `direct_only`
- 若本地成功、懒猫失败，先对比本地与懒猫的 `pull_network_mode` 和 `config_fingerprint`
- 管理台支持“复制配置 JSON / 从配置 JSON 导入”同步标准源配置
- 盒子侧代理桥接见 `docs/operations/lazycat-egress-bridge.md`

### 3.3 策略备份（GitHub 私有仓库）

- `POLICY_BACKUP_ENABLED=true` 后，服务会在“自有策略”变更后自动导出并 push
- 目标仓库建议为空仓库或只包含备份资产目录
- 服务维护的主要路径：
  - `manifest.json`
  - `README.md`
  - `global/custom-rules.yaml`
  - `categories/manual-categories.yaml`
  - `scenarios/<scenario>/...`
- HTTPS 仓库需要把 `POLICY_BACKUP_GITHUB_TOKEN` 配置为懒猫实例的受控运行时
  Secret，并绑定到 `web` 服务进程环境；该值不进入 manifest 或分发包
- `POLICY_BACKUP_SUBDIR` 可用于一仓多环境
- 若当前部署平台无法为 `web` 服务注入该 Secret，应保持
  `POLICY_BACKUP_ENABLED=false`，不要把 token 临时填回 manifest
- 首次上线或轮换后重启实例，执行一次“立即同步”，确认权限与分支配置正确；
  日志和状态只允许显示仓库、分支、提交摘要等非秘密元数据

### 3.4 首次初始化

新安装且尚无已登记工作区时：

- `/` -> `302` 到 `/manage`；管理页面引导当前登录用户初始化
- 登录后可打开 `/setup`，`GET /api/setup/status` 返回当前用户的 `setup_required=true`
- 当前用户未初始化时，管理 API 返回 `409 setup required`
- `/sub/*`、`/rules/*` -> `503 setup required`
- `/healthz` -> `200` 且 `setup_required=true`

初始化步骤：

1. 用懒猫账号访问 `/manage` 的初始化引导或 `/setup`
2. 提交初始化（`POST /api/setup/init`）；服务自动创建当前用户的独立工作区、随机字段密钥和默认设备
3. 进入管理页面，添加来源并复制设备订阅链接；API 返回的 `device_token` / `device_public_id` 仅属于当前用户

初始化成功后：

- 当前用户的 `/api/setup/status` 返回 `setup_required=false`、`initialized=true`；重复初始化保持既有设备身份
- `/healthz` 仍返回 `200`，实例级 `setup_required=false` 只表示已存在工作区，其他用户仍需分别初始化
- 公开订阅按设备 token / public ID 查找所属用户；未知或冲突标识返回 `403`
- 密钥保存在所属工作区的 `data/field_cipher.key`，应与数据库一起保留；旧根目录归属按上节的升级约定处理

### 3.5 订阅与管理入口边界

- 推荐保持 `APP_BASE_URL` 为空，优先使用 `LAZYCAT_APP_DOMAIN`
- 管理后台仅信任懒猫网关注入的登录身份头
- 应用内账号密码登录已下线，不再使用 `ADMIN_USER` / `ADMIN_PASS`
- 本地调试可通过 `X-HC-User-ID` 模拟懒猫身份

### 3.6 长驻 runtime 恢复边界

- `/healthz` 只表示进程仍能响应，同时返回 `runtime_tasks`、`policy_backup` 和有限错误信号；runtime task 原始错误只留在认证诊断面，不能把 HTTP 200 当作 resident worker 正常运行的证明。
- `/healthz` 的 `policy_backup` 仅是匿名安全投影，不返回 repository URL、分支或错误详情；完整策略备份配置只通过认证管理接口读取。
- resident supervisor 会对 resident task 的异常退出立即写 durable fatal receipt；独立 watchdog 周期检查 stale/missing heartbeat，不依赖人工请求 `/readyz` 才告警。
- `/readyz` 会校验 SQLite integrity、required worker heartbeat、主动 HTTPS 告警能力，以及已启用策略备份的 reconcile 状态；任一项失败返回 `503`。告警能力未配置时 `runtime_alerts.ok=false`，不能冒充已具备通知能力。
- 自有策略变更先写 SQLite dirty generation/outbox。进程重启时会比较本地快照 digest 与远端 manifest；外部 Git push 结果不明确时只做 compare/reconcile，匹配前不会确认 generation。
- 策略恢复先在临时 SQLite 文件中应用并通过 integrity/foreign-key 检查，再以短 change-token CAS + `os.replace` 原子切换；CAS token 还包含进程级数据库代次，完整 restore 操作在 repository writer lock 外串行，避免重开 observer connection 后两个重叠 restore 都接受旧快照。若 staging 期间有非策略写入则从新快照重试，避免覆盖 heartbeat、告警 receipt 或 outbox。请用仓库中的本地 fixture 演练验证 readback，不要把备份文件存在当作恢复成功。
- 标准源 worker 在等待共享 refresh lock 时继续 heartbeat；同名 standard-source waiter 使用独立的非 required heartbeat，而 full refresh 排在 standard-source owner 后时保留自己的 required queued heartbeat，owner 自身仍独立判定健康。规则目录与 GoRelay 仅在当前 Hub refresh invocation 的 context token 内、实际子项完成时转发进度，独立 resident/management refresh 不能掩盖 Hub 挂起。`/readyz`、backup 和 staged promotion 的 SQLite checkpoint 使用 PASSIVE，并把完整性扫描移出 event loop；promotion 先持久化 journal，启动时可在 SIGKILL 后恢复 staged database/WAL 边界，避免旧 reader 或大库阻塞 resident heartbeat。

## 4. 持久化目录

- `/lzcapp/var/data/tenant_registry.db`：用户工作区注册表
- `/lzcapp/var/tenants/<sha256-user-id>/`：各用户的数据库、字段密钥、缓存和其他工作区资产
- `/lzcapp/var/data`、`cache`、`logs`：显式绑定旧根目录的用户或本地共享模式使用的历史路径

升级应保留整个 `/lzcapp/var`，同时保留注册表与各用户数据库、字段密钥。

## 5. 启动后验证

```bash
lzc-cli app status cloud.lazycat.subhub
lzc-cli docker -- ps -a | grep cloudlazycatsubhub
lzc-cli docker -- logs cloudlazycatsubhub-web-1 --tail 100
```

公网匿名访问验证：

```bash
curl -i https://<your-app-domain>/healthz
curl -i "https://<your-app-domain>/sub/device/<DEVICE_PUBLIC_ID>/default/shadowrocket-nodes.txt"
curl -i https://<your-app-domain>/manage
```

预期：

- `/healthz` 在初始化前后均返回 `200`
- 初始化后，有效设备标识的节点订阅返回 `200`，未知或冲突标识返回 `403`；尚无工作区时返回 `503 setup required`
- 公开订阅直接返回业务响应；匿名访问 `/manage` 由懒猫网关引导登录

已登录用户验证：

- 可访问 `/manage`；新用户完成初始化后可使用管理 API
- 当前用户只能看到自己的账号和订阅
- 页面生成的订阅链接域名应为 `https://{LAZYCAT_APP_DOMAIN}`

### 1.0.11 契约生命周期升级

升级前保留旧 LPK，并备份完整持久化目录（SQLite 使用一致性备份），数据库必须与字段密钥一起保留。1.0.11 保留既有契约 ID、名称、绑定和作用域，首次迁移取消系统只读保护；后续启动不会补回已删除契约。若从 1.0.9 或更早版本升级，同时遵循上面的旧数据用户归属配置；不得让新空工作区遮蔽已有配置。升级后验证契约动作、引用迁移、重启持久性和已有设备订阅。回滚时包与升级前数据快照成对恢复。

### 1.0.12 玻璃工作台外壳

1.0.12 只替换管理端前端外壳，不改数据库结构、HTTP 接口和订阅输出，升级无需迁移；保留 1.0.11 的 LPK 即可直接回滚。升级后在 `/manage` 确认清透和烟熏两套主题都能切换，配置与场景页在烟熏主题下没有白色控件，并确认已有设备订阅仍返回 `200`。

### 1.0.13 服务目录性能与打包修复

1.0.13 不改数据库结构、HTTP 接口字段和订阅输出，升级无需迁移；保留 1.0.12 的 LPK 即可直接回滚。这一版起 LPK 构建会重建管理端，构建机需先 `npm ci --prefix frontend`。升级后进入服务目录确认表格正常出现，`/manage` 响应带 `Cache-Control: no-cache`，并确认已有设备订阅仍返回 `200`。升级前打开过管理端的浏览器可能仍缓存着旧外壳，首次进入未加载过的工作区若提示分包加载失败，刷新一次即可。

## 6. 版本与发布

- 每次发布提升 `lzc-manifest.yml` 的 `version`
- 同步更新 `docs/governance/changelog.md`
- 发布前运行 `scripts/security_preflight.sh`
