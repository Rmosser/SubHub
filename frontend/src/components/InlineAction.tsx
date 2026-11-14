import Button, { type ButtonProps } from "@cloudscape-design/components/button";

// 链接型动作是没有框的钴蓝文字，和纸上的链接同色：
// - InlineAction：表格行里的“启用”“删除”、纸上的“编辑并检查来源”（不占按钮高度）；
// - LinkAction：对话框里的“取消”、纸上并列的次要动作（保留按钮的点击区）；
// - NameAction：行标题式的名称链接，保持墨色；
// - IconAction：行内图标按钮；
// - IconButton：普通图标按钮（variant="icon"，来源卡片的编辑/删除、复制按钮）。
// Cloudscape 的 inline-link / link 变体默认取普通按钮的墨色，这里用 style 把它拨回钴蓝。
// 窄屏或触屏时点击区扩到 44px，视觉尺寸不变：只加透明内边距（--s-hit-block / --s-hit-inline，桌面为 0），
// 文字类再由 s-hit 给最小宽度。用内边距而不是伪元素：表格单元会裁掉溢出的伪元素，相邻目标也不会互相盖住。
// 普通图标按钮自带 4px 内边距，窄屏或触屏时换成 --s-icon-pad-*（16px 图标 + 22px 行高 + 1px 边框 → 44×44）。
const LINK_COLOR: NonNullable<ButtonProps.Style["root"]>["color"] = {
  default: "var(--g-lit)",
  hover: "var(--s-link-hover)",
  active: "var(--s-link-hover)",
  disabled: "var(--k-muted)",
};

const INLINE_LINK_STYLE: ButtonProps.Style = { root: { color: LINK_COLOR, paddingBlock: "var(--s-hit-block)" } };
// link 变体本身有 4px 上下内边距
const LINK_STYLE: ButtonProps.Style = { root: { color: LINK_COLOR, paddingBlock: "max(4px, var(--s-hit-block))" } };
const NAME_STYLE: ButtonProps.Style = { root: { paddingBlock: "var(--s-hit-block)" } };
const ICON_ACTION_STYLE: ButtonProps.Style = {
  root: { paddingBlock: "var(--s-hit-block)", paddingInline: "calc(4px + var(--s-hit-inline))" },
};
const ICON_BUTTON_STYLE: ButtonProps.Style = {
  root: { paddingBlock: "var(--s-icon-pad-block)", paddingInline: "var(--s-icon-pad-inline)" },
};

type LinkActionProps = Omit<ButtonProps, "variant" | "style">;

const hit = (className?: string) => (className ? `s-hit ${className}` : "s-hit");

export function InlineAction(props: LinkActionProps) {
  return <Button {...props} className={hit(props.className)} variant="inline-link" style={INLINE_LINK_STYLE} />;
}

export function LinkAction(props: LinkActionProps) {
  return <Button {...props} className={hit(props.className)} variant="link" style={LINK_STYLE} />;
}

export function NameAction(props: LinkActionProps) {
  return <Button {...props} className={hit(props.className)} variant="inline-link" style={NAME_STYLE} />;
}

export function IconAction(props: LinkActionProps) {
  return <Button {...props} variant="inline-icon" style={ICON_ACTION_STYLE} />;
}

export function IconButton(props: LinkActionProps) {
  return <Button {...props} variant="icon" style={ICON_BUTTON_STYLE} />;
}
