import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import AppLayout from "@cloudscape-design/components/app-layout";
import { usePrefetchCatalog } from "@/api/queries";
import { AppShellDockProvider } from "@/contexts/AppShellDockContext";
import { ScenarioSelector } from "@/components/ScenarioSelector";
import { GlassMenu } from "@/components/GlassMenu";
import { GlassDrawerLayout } from "@/components/GlassDrawer";
import { SPLIT_PANEL_ID, useSplitPanel } from "@/contexts/SplitPanelContext";
import { useLocale } from "@/contexts/LocaleContext";
import { GlassBackdrop } from "@/glass/GlassBackdrop";
import { useThemePreference, type ThemePreference } from "@/theme/glassTheme";
import { AnimatedOutlet, SLIDE_RIGHT, REDUCED_FADE, SPRING_DEFAULT, REDUCED_INSTANT, useMotionReady } from "@/motion";
import "@/styles/glass.css";

const NAV_GROUPS = [
  { id: "workspace", en: "Workspace", zh: "订阅工作台", items: [
    { path: "/sources", en: "Sources", zh: "订阅源" },
    { path: "/devices", en: "Devices", zh: "设备交付" },
    { path: "/catalog", en: "Service catalog", zh: "服务目录" },
  ] },
  { id: "policy", en: "Policy", zh: "路由与配置", items: [
    { path: "/contracts", en: "Route contracts", zh: "路由契约" },
    { path: "/pools", en: "Node pools", zh: "节点池" },
    { path: "/profile", en: "Profile & scenarios", zh: "配置与场景" },
  ] },
  { id: "operations", en: "Operations", zh: "管理与诊断", items: [
    { path: "/review", en: "Review", zh: "审核对比" },
    { path: "/llm", en: "LLM workflows", zh: "LLM 工作流" },
    { path: "/advanced", en: "Advanced", zh: "高级设置" },
  ] },
] as const;

const THEME_OPTIONS: ReadonlyArray<{ id: ThemePreference; zh: string; en: string; zhName: string; enName: string }> = [
  { id: "system", zh: "自动", en: "Auto", zhName: "自动（跟随系统）", enName: "Auto (follow system)" },
  { id: "light", zh: "清透", en: "Clear", zhName: "清透（浅色）", enName: "Clear (light)" },
  { id: "dark", zh: "烟熏", en: "Smoke", zhName: "烟熏（深色）", enName: "Smoke (dark)" },
];

function BrandMark() {
  return (
    <svg className="glass-brand-mark" viewBox="222 222 580 580" aria-hidden="true">
      <g fill="currentColor" stroke="currentColor" strokeWidth="84" strokeLinejoin="round">
        <polygon points="323,441.1 349,435.6 349,657.7 323,663.2" />
        <polygon points="499,293.7 525,288.2 525,730.3 499,735.8" />
        <polygon points="675,322.3 701,316.8 701,626.9 675,632.4" />
      </g>
    </svg>
  );
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { locale, setLocale: switchLocale, t } = useLocale();
  const { splitPanel, closeSplitPanel } = useSplitPanel();
  const [dockContent, setDockContent] = useState<ReactNode | null>(null);
  const [themePref, setThemePref] = useThemePreference();
  const railRef = useRef<HTMLElement>(null);
  const { shouldAnimate } = useMotionReady();
  const isZh = locale === "zh-CN";
  const variants = shouldAnimate ? SLIDE_RIGHT : REDUCED_FADE;
  const transition = shouldAnimate ? SPRING_DEFAULT : REDUCED_INSTANT;
  const dockContextValue = useMemo(() => ({ setDockContent }), [setDockContent]);
  // 数据量大的工作区在导航项悬停或聚焦时就开始取数据，挂载时不用再等请求
  const prefetchCatalog = usePrefetchCatalog();
  const prefetchByPath: Partial<Record<string, () => void>> = { "/catalog": prefetchCatalog };
  // 窄屏导航是一行横向滚动：换页后把当前项带进可见范围
  useEffect(() => {
    const groups = railRef.current?.querySelector<HTMLElement>(".glass-groups");
    const active = groups?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!groups || !active || groups.scrollWidth <= groups.clientWidth) return;
    const g = groups.getBoundingClientRect(), a = active.getBoundingClientRect();
    if (a.left < g.left || a.right > g.right - 48) groups.scrollLeft += a.left - g.left - 24;
  }, [location.pathname]);
  // 已在配置页时保留现有查询参数（设备、读图层级等），只设置 section。
  // 读图把手机所在位置直接写进地址栏、不经路由，所以这里读 window.location 而不是路由的 location。
  const handleScenarioNavigation = (action: "focus" | "create") => {
    const params = new URLSearchParams(location.pathname === "/profile" ? window.location.search : "");
    params.set("section", "scenarios");
    navigate({ pathname: "/profile", search: `?${params.toString()}` }, { state: { scenarioAction: action, scenarioNavNonce: Date.now() } });
  };

  return (
    <AppShellDockProvider value={dockContextValue}>
      <GlassBackdrop railRef={railRef} />
      <div className="glass-app">
        <header ref={railRef} className="glass-rail">
          <Link className="glass-brand" to="/sources" aria-label="SubHub">
            <BrandMark /><span className="glass-brand-word" data-glass-etch>SubHub</span>
          </Link>
          <div className="glass-context">
            <div className="glass-context-head">
              <span className="glass-label" data-glass-etch>{isZh ? "场景" : "Scenario"}</span>
              <GlassMenu ariaLabel={t("scenario.manage")} items={[
                { id: "focus", text: t("scenario.manage") }, { id: "create", text: t("scenario.create") },
              ]} onItem={(id) => handleScenarioNavigation(id as "focus" | "create")} />
            </div>
            <ScenarioSelector compact hideLabel stretch label={t("scenario.current")} />
          </div>
          <nav className="glass-groups" aria-label={isZh ? "工作区导航" : "Workspace navigation"}>
            {NAV_GROUPS.map((group) => (
              <div key={group.id} className="glass-group" role="group" aria-labelledby={`glass-nav-${group.id}`}>
                <p className="glass-label" id={`glass-nav-${group.id}`} data-glass-etch>{isZh ? group.zh : group.en}</p>
                {group.items.map((item) => {
                  const active = location.pathname === item.path;
                  const prefetch = prefetchByPath[item.path];
                  return (
                    <Link key={item.path} to={item.path} className="glass-item" data-glass-item data-glass-etch aria-current={active ? "page" : undefined} onPointerEnter={prefetch} onFocus={prefetch}>
                      {isZh ? item.zh : item.en}
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>
          <div className="glass-foot">
            <div className="glass-seg" role="group" aria-label={isZh ? "外观" : "Appearance"}>
              {THEME_OPTIONS.map((opt) => (
                <button key={opt.id} type="button" aria-pressed={themePref === opt.id} aria-label={isZh ? opt.zhName : opt.enName} onClick={() => setThemePref(opt.id)}>
                  {isZh ? opt.zh : opt.en}
                </button>
              ))}
            </div>
            <button type="button" className="glass-chip" lang={isZh ? "en" : "zh-CN"} aria-label={isZh ? "Switch to English" : "切换到中文"} onClick={() => switchLocale(isZh ? "en-US" : "zh-CN")}>
              {isZh ? "EN" : "中文"}
            </button>
          </div>
        </header>
        <div className="glass-main">
          <GlassDrawerLayout
            open={splitPanel.isOpen}
            id={SPLIT_PANEL_ID}
            header={splitPanel.header}
            contentKey={splitPanel.contentKey}
            strings={{ close: isZh ? "关闭详情面板" : "Close detail panel", resize: isZh ? "调整详情面板大小" : "Resize detail panel" }}
            onClose={closeSplitPanel}
            content={<AnimatePresence mode="wait"><motion.div key={splitPanel.contentKey} initial={variants.initial} animate={variants.animate} exit={variants.exit} transition={transition}>{splitPanel.content}</motion.div></AnimatePresence>}
          >
            <AppLayout
              contentType="default"
              maxContentWidth={1400}
              minContentWidth={0}
              navigationHide
              toolsHide
              ariaLabels={{ navigation: isZh ? "工作区导航" : "Workspace navigation", navigationToggle: isZh ? "展开导航" : "Open navigation", navigationClose: isZh ? "收起导航" : "Close navigation" }}
              content={<AnimatedOutlet />}
            />
          </GlassDrawerLayout>
        </div>
        <AnimatePresence>{dockContent ? <motion.div key="app-shell-dock" className="app-shell-dock" initial={shouldAnimate ? { opacity: 0, y: -8 } : undefined} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={transition}><div className="app-shell-dock-content">{dockContent}</div></motion.div> : null}</AnimatePresence>
      </div>
    </AppShellDockProvider>
  );
}
