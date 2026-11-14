# LazyCat Internal Proxy Bridge

适用场景：

- `cloud.lazycat.subhub` 这类业务服务需要默认可走代理
- GoRelay 上游必须通过代理访问
- 标准源又需要按 `pull_network_mode` 保留真直连能力

推荐拓扑：

1. 在懒猫盒子上准备本地 Mihomo 监听，默认 `127.0.0.1:7890`
2. 用盒子桥地址额外暴露一个仅容器可达的入口：`172.18.0.1:17890`
3. 给 `subhub` 的 `web` 服务注入 `HTTP_PROXY/HTTPS_PROXY`
4. 业务代码按请求显式选择 `trust_env=True/False`

## SubHub 内置诊断语义

SubHub 自己会在这些接口里输出同一份桥接代理诊断：

- `GET /healthz`
- `GET /diagnostics`
- `GET /api/status`

核心字段语义：

- `summary`：一句话告诉你“现在是什么故障”
- `meaning`：解释故障落在哪一层，是缺环境、桥接入口不可达，还是上游 Mihomo 已掉
- `repair_hint`：最短修复路径
- `actions`：按顺序执行的动作列表

常见 `code`：

- `missing_proxy_env`
  - 含义：SubHub 进程里根本没有 `HTTP_PROXY/HTTPS_PROXY`
  - 修法：检查 manifest 是否已注入代理环境并重新部署
- `proxy_bridge_unreachable`
  - 含义：SubHub 容器连不到 `172.18.0.1:17890`
  - 修法：先跑 `check_mihomo_bridge.sh`，再恢复 `mihomo-container-proxy.socket`
- `proxy_bridge_upstream_failed`
  - 含义：桥接 socket 还活着，但通过它发出的 HTTPS 代理探测失败
  - 修法：去查 Mihomo/Clash MiHome 本地监听是否还在、端口是否变了
- `ok`
  - 含义：桥接代理和 HTTPS 探测都通过
  - 修法：如果 GoRelay 仍失败，转查上游鉴权或接口配置

## 安装桥接入口

仓库内提供安装脚本：

```bash
sudo bash scripts/lazycat-proxy-bridge/install_mihomo_bridge.sh --install --confirm --target-host 127.0.0.1
```

绑定地址、端口、unit 名和 `systemd-socket-proxyd` 路径由脚本固定；不带
`--install --confirm` 时只输出计划，不写 systemd。

## 盒子侧验证

```bash
ss -ltnp | grep '172.18.0.1:17890'
ss -ltnp | grep '0.0.0.0:17890' && echo "BAD public bind" && exit 1 || true
curl -sS -o /dev/null -w "%{http_code}\n" -I -x http://172.18.0.1:17890 https://api.openai.com/v1/models
```

预期：

- 第一条命令能看到监听
- 第二条命令没有输出
- 第三条命令返回 `401` 或其他上游正常响应码，不应是 TLS/连接失败

仓库内也提供一条盒子侧自检脚本：

```bash
sudo bash scripts/lazycat-proxy-bridge/check_mihomo_bridge.sh
```

## SubHub 验证

部署后进入容器确认代理环境：

```bash
lzc-cli docker -- exec cloudlazycatsubhub-web-1 sh -lc 'env | sort | grep -Ei "proxy|no_proxy"'
```

再在管理后台手动拉取：

- GoRelay 源应恢复可达
- 标准源设为 `direct_only` 后，`pull_result.attempts[*].network_path` 只能出现 `direct`

## 掉了怎么办

先判定是哪一层掉了：

1. 桥接 socket 掉了
2. Mihomo 上游掉了
3. SubHub 没吃到代理环境变量
4. 其实不是代理问题，而是标准源格式/解析问题

### 1. 桥接 socket 掉了

盒子上执行：

```bash
sudo bash scripts/lazycat-proxy-bridge/check_mihomo_bridge.sh
```

如果 `systemctl is-active mihomo-container-proxy.socket` 失败，先恢复：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-container-proxy.socket
sudo systemctl restart mihomo-container-proxy.socket
```

### 2. 桥接还在，但上游 Mihomo 掉了

典型现象：

- `ss` 能看到 `172.18.0.1:17890`
- 但 `curl -I -x http://172.18.0.1:17890 https://api.openai.com/v1/models` 返回 `000` 或连接失败

处理方式：

- 先检查 Mihomo/Clash MiHome 自身是否还在提供本地代理监听
- 默认目标是 `127.0.0.1:7890`
- 桥接目标端口由脚本固定为 `7890`；如果上游端口变更，先更新经过 review 的脚本/配置，再重新运行安装流程，不能通过环境变量覆盖

```bash
sudo bash scripts/lazycat-proxy-bridge/install_mihomo_bridge.sh --install --confirm --target-host 127.0.0.1
```

### 3. 盒子桥接正常，但 SubHub 没走代理

检查容器环境：

```bash
lzc-cli docker -- exec cloudlazycatsubhub-web-1 sh -lc 'env | sort | grep -Ei "proxy|no_proxy"'
```

如果没有 `HTTP_PROXY/HTTPS_PROXY`，说明应用还没重新部署，或运行中的包不是最新 manifest。

### 4. 其实不是代理掉了

如果标准源设置为 `direct_only`，看到的失败应仍然是 `network_path=direct`。  
这类失败常见是：

- 机场订阅源本身不允许直连
- 返回格式不兼容
- 拉到了内容但 `0 valid nodes parsed`

这时不要先重启桥接，先看 `pull_result.attempts[*]`。

## 恢复目标

恢复后的最小验收：

- 盒子上 `check_mihomo_bridge.sh` 通过
- `cloudlazycatsubhub-web-1` 内能看到 `HTTP_PROXY/HTTPS_PROXY`
- GoRelay 手动拉取恢复
- 标准源 `direct_only` 手动拉取的 `attempts[*].network_path` 仍只有 `direct`

## 注意事项

- 不要把 `subhub` 直接指向另一个微服容器名或私网 IP
- `heiyu.space` 的客户端 `DIRECT` 规则只影响客户端访问 SubHub，不影响 SubHub 服务端抓取上游
- 如果 Clash MiHome 目前没有盒子本地监听，先给它补一个 host-local 监听，再执行本桥接脚本
