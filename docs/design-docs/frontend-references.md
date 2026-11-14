# 前端参考项目（`docs/参考项目/`）

目标：为控制台 UI 重构建立分层参考体系——骨架、微交互、点睛三层。
核心理念：冷静控制台 + 高级微交互，不是"满屏特效"。

## 第一层：控制台骨架参考

| 仓库 | 本地路径 | 说明 |
|------|---------|------|
| `cloudscape-design/components` | `docs/参考项目/components-main/` | **骨架第一参考**。AWS 开源云应用设计系统的 React 组件库。重点看：App layout toolbar、Split panel、Flashbar、Property filter、Content density |
| `cloudscape-design/demos` | `docs/参考项目/demos/` | Cloudscape 完整页面 demo 集合。重点看：资源列表页、split view 页、密度切换、过滤保存视图 |
| `backstage/backstage` | _(仅引用，未下载)_ | 开源 developer portal framework。学习：左侧导航层级、资源目录信息密度、"工作台"气质。GitHub: https://github.com/backstage/backstage |
| `grafana/grafana` | _(仅引用，未下载)_ | 开源 observability 平台。学习：数据密集但不乱、状态/筛选/面板切换的克制、专业工具气质。GitHub: https://github.com/grafana/grafana |

## 第二层：高级微交互参考

| 仓库 | 本地路径 | 说明 |
|------|---------|------|
| `motiondivision/motion` | `docs/参考项目/motion/` | **主动画库**。重点能力：`layout`、`layoutId`、`AnimatePresence`、`useReducedMotion`。适合 split panel、row expand、tab underline、inspector 切换 |
| `imskyleen/animate-ui` | `docs/参考项目/animate-ui/` | 全动画开源组件集（React + TypeScript + Tailwind + Motion）。参考：面板进出场、交互控件轻动效、现代产品级写法 |
| `formkit/auto-animate` | `docs/参考项目/auto-animate/` | 零配置 drop-in 动画工具。适合：设备列表刷新、过滤条件出现/消失、告警条增减、表单字段条件显示、小卡片重排 |
| `emilkowalski/sonner` | `docs/参考项目/sonner/` | 高品质 toast 组件。学习：通知出现/退出节奏、堆叠方式、不抢主内容的利落反馈。适用于拉取失败、编译完成、规则更新、同步异常等场景 |
| `floating-ui/floating-ui` | `docs/参考项目/floating-ui/` | 浮层定位库。解决 tooltip、popover、dropdown 等定位和可访问性基础，再叠 Motion 做入场退场 |
| `aholachek/react-flip-toolkit` | `docs/参考项目/react-flip-toolkit/` | FLIP / magic-move / stagger 专项参考。适合：表格/列表重排、过滤后行项目重排、策略组顺序变化 |

## 第三层：局部点睛参考（只借 5%–10% 灵感）

| 仓库 | 本地路径 | 说明 |
|------|---------|------|
| `magicuidesign/magicui` | `docs/参考项目/magicui/` | 面向 design engineers 的动画组件库。适合借：loading shimmer、subtle glow、空状态轻量背景动态、顶部状态灯。**不要照搬**营销页感特效 |
| `educlopez/smoothui` | `docs/参考项目/smoothui/` | React + Tailwind + Motion 动画组件集合。比 Magic UI 更稳，参考：hover/press/reveal 细节、面板圆角/阴影/渐隐过渡 |

## 可选参考

| 仓库 | 本地路径 | 说明 |
|------|---------|------|
| `TanStack/router` | `docs/参考项目/router/` | 路由级 view-transitions 示例。**建议先做局部过渡，再做路由过渡** |

## 推荐技术组合

```
骨架层:     Cloudscape 模式布局（components + demos）
主动画层:   Motion（motiondivision/motion）
浮层交互层: Radix / shadcn 体系 + Floating UI（定位和可访问性）
反馈层:     Sonner
默认顺滑层: AutoAnimate
可选增强:   TanStack Router view-transitions / react-flip-toolkit / animate-ui·smoothui·magicui 局部摘取
```

## 动效落位原则

**"高级感"五条定义：**
1. 空间连续 — 选中设备后 inspector "接出来"，不是突然出现
2. 状态有生命但不吵 — 刷新/编译/失败/成功有轻微明确过渡
3. 动效只服务层级变化 — 抽屉/popover/toast/分栏/表格行展开该动；纯静态不动
4. 重叠层才有更强动势 — 阴影和强 motion 优先给 split panel/drawer/popover/toast/dialog
5. 关掉动效后 UI 仍成立 — 尊重 reduced motion，位移可替换为 opacity

**必须做：** 左侧导航选中态过渡、顶部告警条出现/折叠、表格筛选结果重排、右侧 inspector/split panel 推出、行展开详情、状态 badge 过渡（pending→success/warning/failed）、toast
**可以做但要轻：** tab underline 共享过渡、按钮 hover/press、skeleton/shimmer、编译进度条
**尽量别做重：** 整页大切场、大面积 blur+glow、表格每行夸张位移、高频粒子/扫描线/霓虹拖尾
