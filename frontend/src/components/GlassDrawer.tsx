import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import Button, { type ButtonProps } from "@cloudscape-design/components/button";
import { escapeBelongsToPopup } from "./drawerKeys";

// 详情抽屉：和对话框同一层底——一块磨砂玻璃面板，背后的内容被模糊掉，不透字。
// 宽屏放在内容右侧（内容让位，不叠）；窄屏贴在视口底部（盖住的内容可以继续滚上来）。
// 不抢焦点：打开时焦点留在触发处；关闭（按钮或焦点在抽屉内按 Esc）时焦点回到打开前的位置。
// 尺寸都是抽屉面板实际渲染的宽（侧边）或高（贴底），与分隔条的 aria-value* 一致；
// 上下限与 surfaces.css 的 min()/max() 同一套数：侧边给内容至少留 SIDE_ROOM，底部给页面至少留 SHEET_ROOM。
const SIDE_QUERY = "(min-width: 1200px)";
const SIDE_WIDTH = { initial: 464, min: 344, max: 844, step: 24 };
const SHEET_HEIGHT = { initial: 420, min: 200, max: 900, step: 24 };
const SIDE_ROOM = 520;
const SHEET_ROOM = 96;
// 关闭按钮：窄屏或触屏时点击区 44×44，图标位置不变（内边距在 surfaces.css 里随媒体查询变，s-drawer-close 用负外边距抵消）
const CLOSE_STYLE: ButtonProps.Style = { root: { paddingBlock: "var(--s-icon-pad-block)", paddingInline: "var(--s-close-pad-inline)" } };

type Placement = "side" | "bottom";

function subscribeSide(onChange: () => void) {
  const query = window.matchMedia(SIDE_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function usePlacement(): Placement {
  return useSyncExternalStore(subscribeSide, () => (window.matchMedia(SIDE_QUERY).matches ? "side" : "bottom"), () => "side");
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export interface GlassDrawerStrings {
  close: string;
  resize: string;
}

interface GlassDrawerLayoutProps {
  children: ReactNode;
  open: boolean;
  /** 抽屉面板的 id：触发按钮用 aria-controls 指向它 */
  id: string;
  header: string;
  content: ReactNode;
  contentKey: string;
  strings: GlassDrawerStrings;
  onClose: () => void;
}

export function GlassDrawerLayout({ children, open, id, header, content, contentKey, strings, onClose }: GlassDrawerLayoutProps) {
  const placement = usePlacement();
  const [width, setWidth] = useState(SIDE_WIDTH.initial);
  const [height, setHeight] = useState(SHEET_HEIGHT.initial);
  const hostStyle = { "--s-drawer-w": `${width}px`, "--s-drawer-h": `${height}px` } as CSSProperties;

  return (
    <div className="s-drawer-host" data-drawer={open ? placement : undefined} style={hostStyle}>
      <div className="s-drawer-main">{children}</div>
      {open ? (
        <GlassDrawer
          id={id}
          placement={placement}
          header={header}
          contentKey={contentKey}
          strings={strings}
          size={placement === "side" ? width : height}
          onResize={placement === "side" ? setWidth : setHeight}
          onClose={onClose}
        >
          {content}
        </GlassDrawer>
      ) : null}
    </div>
  );
}

interface GlassDrawerProps {
  id: string;
  placement: Placement;
  header: string;
  contentKey: string;
  children: ReactNode;
  strings: GlassDrawerStrings;
  size: number;
  onResize: (size: number) => void;
  onClose: () => void;
}

// 当前方位下面板能取到的最大尺寸：侧边按宿主内容区宽，底部按视口高
function roomFor(placement: Placement, host: HTMLElement | null | undefined) {
  if (placement === "bottom") return window.innerHeight - SHEET_ROOM;
  if (!host) return window.innerWidth - SIDE_ROOM;
  const style = getComputedStyle(host);
  return host.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - SIDE_ROOM;
}

function GlassDrawer({ id, placement, header, contentKey, children, strings, size, onResize, onClose }: GlassDrawerProps) {
  const titleId = useId();
  const asideRef = useRef<HTMLElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef<{ start: number; size: number; max: number } | null>(null);
  const bounds = placement === "side" ? SIDE_WIDTH : SHEET_HEIGHT;
  // 实际上限随视口变，按方位记：宽窄切换后旧方位量到的值不再算数
  const [measured, setMeasured] = useState<{ placement: Placement; max: number } | null>(null);
  const maxSize = measured?.placement === placement ? measured.max : bounds.max;
  const readMax = useCallback(() => clamp(roomFor(placement, asideRef.current?.parentElement), bounds.min, bounds.max), [placement, bounds]);

  // 挂载时（绘制前）就量一次，之后跟着视口与宿主宽度变化
  useLayoutEffect(() => {
    const update = () => {
      const max = readMax();
      setMeasured((prev) => (prev?.placement === placement && prev.max === max ? prev : { placement, max }));
    };
    update();
    const host = asideRef.current?.parentElement;
    const observer = typeof ResizeObserver === "undefined" || !host ? null : new ResizeObserver(update);
    if (host) observer?.observe(host);
    window.addEventListener("resize", update);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [placement, readMax]);

  // 记住每次打开（或换内容）时的触发处；焦点已在抽屉里时不覆盖。StrictMode 二次执行读到的是同一个元素
  useEffect(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement && active !== document.body && !asideRef.current?.contains(active)) openerRef.current = active;
  }, [contentKey]);

  const close = useCallback(() => {
    const opener = openerRef.current;
    const focusInside = asideRef.current?.contains(document.activeElement) ?? false;
    onClose();
    if (focusInside && opener?.isConnected) opener.focus({ preventScroll: true });
  }, [onClose]);

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.defaultPrevented || event.nativeEvent.isComposing) return;
    // 抽屉里展开着的下拉、菜单先收自己；普通的展开按钮不拦
    if (escapeBelongsToPopup(event.target as HTMLElement, event.currentTarget)) return;
    event.preventDefault();
    close();
  };

  const current = Math.min(size, maxSize);
  const resizeBy = (delta: number) => onResize(clamp(current + delta, bounds.min, readMax()));

  const handleSeparatorKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const grow = placement === "side" ? "ArrowLeft" : "ArrowUp";
    const shrink = placement === "side" ? "ArrowRight" : "ArrowDown";
    if (event.key === grow) resizeBy(bounds.step);
    else if (event.key === shrink) resizeBy(-bounds.step);
    else if (event.key === "Home") onResize(bounds.min);
    else if (event.key === "End") onResize(readMax());
    else return;
    event.preventDefault();
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { start: placement === "side" ? event.clientX : event.clientY, size: current, max: readMax() };
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const position = placement === "side" ? event.clientX : event.clientY;
    onResize(clamp(drag.size + drag.start - position, bounds.min, drag.max));
  };
  const endDrag = () => { dragRef.current = null; };

  return (
    <aside ref={asideRef} id={id} className="s-drawer" data-placement={placement} aria-labelledby={titleId} onKeyDown={handleKeyDown}>
      <div
        className="s-drawer-handle"
        role="separator"
        tabIndex={0}
        aria-label={strings.resize}
        aria-orientation={placement === "side" ? "vertical" : "horizontal"}
        aria-valuemin={bounds.min}
        aria-valuemax={maxSize}
        aria-valuenow={current}
        onKeyDown={handleSeparatorKey}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      />
      <div className="s-drawer-head">
        <h2 id={titleId} className="s-drawer-title">{header}</h2>
        <Button className="s-drawer-close" variant="icon" iconName="close" ariaLabel={strings.close} style={CLOSE_STYLE} onClick={close} />
      </div>
      <div className="s-drawer-body">{children}</div>
    </aside>
  );
}
