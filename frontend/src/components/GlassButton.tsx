import { forwardRef } from "react";

// 玻璃上的按钮，和 Cloudscape 的墨色主按钮配套：
// - glass：一小块玻璃，片上的「重新拉取」、折叠区里的次要操作；
// - ghost：刻字行上的轻操作（「拉取」），悬停才亮；
// - quiet：没有底的光色文字（「编辑来源」）。
// busy 时文字留位、换成一个小转圈，按钮宽度不跳。
export type GlassButtonVariant = "glass" | "ghost" | "quiet";

interface Props extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  variant?: GlassButtonVariant;
  busy?: boolean;
  type?: "button" | "submit";
}

export const GlassButton = forwardRef<HTMLButtonElement, Props>(function GlassButton(
  { variant = "glass", busy = false, className, children, onClick, type = "button", ...rest },
  ref,
) {
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={["s-btn", variant, className ?? ""].filter(Boolean).join(" ")}
      aria-busy={busy || undefined}
      onClick={(event) => { if (!busy) onClick?.(event); }}
    >
      <span className="s-btn-text">{children}</span>
      {busy ? <span className="s-btn-spin" aria-hidden="true" /> : null}
    </button>
  );
});
