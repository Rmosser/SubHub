# client-ui-replica — 代理客户端设置界面素材

用于重做 SubHub「配置与场景」页：左边按像素复刻客户端设置界面，右边写 SubHub 的说明。界面树（inventory）是数据，像素外观（replica）是渲染层，两者分开。

本目录在 `docs/` 之外，不进 LPK。参考截图来自日常在用的真机，含真实配置，**只留在本地**：`screens/` 和 `replica/out/` 在 `.gitignore` 里。新机器上没有截图时，inventory、tokens、复刻页照常能用，只是 `compare.py` 没法比对。

## 采集环境

| 项 | 值 |
| --- | --- |
| 日期 | 2026-11-11 |
| 设备 | iPhone 17 Pro，通过 macOS iPhone 镜像只读遍历 |
| iOS | 27.2.1（2026-11-11 经用户同意，在 设置 › 通用 › 关于本机 只读查看） |
| Shadowrocket | 2.2.93 (3488) |
| Surge iOS | 5.23.0 (3867)，未启动 VPN |
| Clash Mi | 1.0.31.1703，内核 mihomo 1.19.32（开发者 Supernova Nebula LLC）；2026-11-11 经用户同意从 App Store 重新下载，新装、未导入配置、未连接 |
| Clash | 1.0.14 (178)，内核 1.19.33：Clash Mi 装上之前用的替代品，数据保留在 `clash` 名下 |

## px ↔ pt

截图为 619×1357 px（镜像窗口原样）。手机屏占 x 8–610、y 38–1348，即 402×874 pt。
**1 pt = 1.5 px，原点 (8, 38)**：`pt = ((px_x − 8) / 1.5, (px_y − 38) / 1.5)`。早期估算的 1.54 不对，以 1.5 为准。

## 目录

| 路径 | 内容 |
| --- | --- |
| `inventory/<app>.json` | UI 树数据：screen → group → row（label / control / value / layer / subhub / maps_to）；敏感值 `<redacted>` |
| `inventory/_notes/` | 手工整理的一手数据（如 Shadowrocket 主题色），生成器读它 |
| `screens/<app>/<id>.png` | 截图（仅本地，不进 git）；文件名对应 inventory 的 screen id，长页带 `_1`、`_2` |
| `tokens/<app>.json` | 实测尺寸与颜色（pt），每项附测量方法与误差；手工维护 |
| `replica/` | HTML/CSS iOS 列表套件（`kit.css` / `kit.js`）、复刻页、`data/`（生成）、`build_data.py`、`compare.py` |
| `tools/` | inventory 生成器（`common.py` + 每个 App 一个脚本）、截图与测量工具 |
| `coverage.md` | 覆盖 / 未覆盖及原因、涂黑记录、与 app-guide 不一致处 |

## 怎么用 / 怎么改

inventory 和 replica/data 都是生成物，改源头再重新生成，不要手改 JSON：

```bash
# 1. 改 tools/<app>.py 后重新生成 inventory（在 tools/ 里跑，脚本用 from common import *）
cd design/client-ui-replica/tools && ../../../.venv/bin/python surge.py && cd -
# 2. 改 inventory / tokens / build_data.py 后重新生成复刻数据
./.venv/bin/python design/client-ui-replica/replica/build_data.py
# 3. 校验：生成物与提交一致、取值封闭、没有明显的敏感值
./.venv/bin/python -m pytest tests/test_client_ui_replica.py -q
```

复刻页直接用浏览器打开 `replica/<app>-<screen>.html`；加 `#ann` 显示每行与 SubHub 的关系。

新增一屏复刻：在 `build_data.py` 加一个函数并登记到末尾列表，复制一个现有 `.html` 改 data 文件名，然后跑 `compare.py <name>` 看叠图和分数。

重新采集（需要 iPhone 镜像和本机截图）：

| 工具 | 用途 |
| --- | --- |
| `tools/cap.sh <app> <id>` | 截镜像窗口到 `screens/<app>/<id>.png`；`WID` 环境变量指定窗口号 |
| `tools/redact.py <png> x0,y0,x1,y1 …` | 按窗口像素坐标涂黑（Secret、订阅 URL、节点详情等） |
| `tools/measure.py` | 量行高、分隔线、颜色等几何 |
| `tools/rowcmp.py <ref> <render> [x_pt]` | 竖向色段 + 文字行位置对比，定位复刻偏差 |

敏感值只记结构，值写 `<redacted>`。

`subhub` 取值：`writes` 写入、`partial` 只写一部分、`none` 不写、`device` 只在手机本机、`unverified` 还没核对、`na` 不适用（动作或导航）。

## 覆盖

| App | 屏 | 行 | 截图 | 写入 | 只写一部分 | 不写 | 只在本机 | 还没核对 | 不适用 |
| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| Shadowrocket | 68 | 397 | 82 | 60 | 9 | 34 | 202 | 43 | 49 |
| Surge iOS | 38 | 244 | 57 | 57 | 4 | 53 | 43 | 18 | 69 |
| Clash（替代品） | 20 | 221 | 33 | 49 | 4 | 56 | 40 | 13 | 59 |
| Clash Mi | 15 | 107 | 18 | 0 | 0 | 24 | 67 | 1 | 15 |

## replica

数据与渲染分开：`build_data.py` 读 inventory + tokens 生成 `data/<app>-<screen>.js`；`kit.js` 只负责画，界面文字全来自数据；图标是自己画的 SVG。

```bash
./.venv/bin/python design/client-ui-replica/replica/build_data.py
./.venv/bin/python design/client-ui-replica/replica/compare.py shadowrocket-config-edit
```

`compare.py` 用 headless Chrome 以 402×874 @1.5x 渲染，与参考截图比对，输出 `out/<name>-render / -overlay / -diff / -side.png`。打开 `shadowrocket-config-edit.html#ann` 显示每行与 SubHub 的关系标记。

已做 5 屏（2026-11-11 复核后）：

| 屏 | 参考截图 | 全屏平均差 | 列表区平均差 | 列表区 ≤16 占比 | 列表区模糊 1.2 px 后平均差 |
| --- | --- | --: | --: | --: | --: |
| shadowrocket-config-edit | shadowrocket/config-edit_1 | 4.21 | 2.65 | 97.2% | 1.30 |
| surge-more-advanced | surge/more-advanced_1 | 5.70 | 4.96 | 95.1% | 2.66 |
| surge-more-advanced-scrolled | surge/more-advanced_2 | 6.82 | 7.60 | 92.3% | 4.26 |
| clash-profile-global | clash/profile-global_1 | 5.60 | 5.27 | 94.2% | 3.06 |
| clash-mi-core-settings | clash-mi/core-settings_1 | 5.21 | 4.80 | 93.9% | 2.74 |

「模糊后平均差」：镜像截图是视频流，文字边缘比 Chrome 软；两边各模糊 1.2 px 再比，主要反映几何与颜色误差。逐行文字墨迹框与参考图差 ≤1.5 pt（个别 2.7 pt，见下）。

已知差异：

- 状态栏：图标是自绘的，没画专注模式（床）图标和充电闪电。
- Chrome 的 SF 字体里「Wi-Fi」的连字符、中英文间空格比 iOS 宽：Surge「允许 Wi-Fi 访问」宽 7 pt；Clash「默认 · 5 分钟」宽 6 pt。
- Surge 的 Wi-Fi IP 副标题按 inventory 显示 `<局域网 IP>`，不显示真实 IP。
- Surge 滚动屏：导航材质下透出的「接管模式」虚影和滚动条没画。
- Clash：悬浮搜索框的玻璃模糊比真机弱；「连接」组的开关行文字低 1–2 pt。
- Shadowrocket：Tab 栏底下透出的「编辑纯文本」虚影没画。
- Clash Mi：
  - Secret 在参考图里已涂黑，复刻图在同一位置画同样的黑块。
  - ⓘ 图标和右上文档图标是自绘的，线宽与原图略有差别。

复核中改正的错误：

- build_data.py 原来把 Shadowrocket 的首组顶部和组间距写死成 130 / 36.7，没读 tokens。tokens 里本来就是 132 / 37.3；行高改成实测的 48.8。
- Shadowrocket 颜色改用截图实测值。Tab 栏：未选中图标 #877676，文字近黑。
- Surge：
  - 行高 52.9 → 53.0。
  - 按钮中心 98 → 100.3。
  - 首卡片 188 → 187.4。
  - 关闭态开关轨道 #E9E9EB → #C5C5C7。
  - 分隔线右侧也内缩 20。
- Clash：按钮中心 108 → 110；行高 52 → 52.3；关闭态开关轨道改为 #C5C5C7。
- 屏幕四角按 64 pt 圆角，灵动岛按实测 138.7–263.3 × 14.7–49.3。
- Surge「数据包捕获」卡片的脚注原来记成 `TCP|UDP|ICMP`，真机是 `TCP/UDP/ICMP`。
