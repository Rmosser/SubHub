import { applyTheme } from "@cloudscape-design/components/theming";

// Cloudscape and our own surfaces share the same supported theme values.
// 外壳是一块玻璃：布局底色透明，内容放在玻璃片上，主操作是墨，深色（烟熏）由 Cloudscape dark mode 承接。
// 这里的取值与 glass.css 的 --k-* / --p-* / --g-lit 一致；改一边要同步另一边。
export const workbenchTokens = {
  sans: '"Geist", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif',
  mono: '"Geist Mono", "SFMono-Regular", ui-monospace, Menlo, Consolas, monospace',
  ink: "#10211f",
  muted: "#4c5f5c",
  lit: "#1846c4",
  link: "#1f4fc8",
  linkHover: "#163ea3",
  rule: "rgba(9, 22, 30, 0.13)",
  inkButton: "#10211f",
  inkButtonHover: "#1f3a36",
  inkButtonActive: "#0a1715",
  inkButtonText: "#f4f7f5",
} as const;

const smoke = {
  ink: "#dbe7e4",
  heading: "#eef5f3",
  muted: "#9db0ab",
  lit: "#d6e3ff",
  link: "#b3c9ff",
  linkHover: "#d6e3ff",
  rule: "rgba(214, 232, 227, 0.12)",
  inkButton: "#dce7e3",
  inkButtonHover: "#eef4f2",
  inkButtonActive: "#c9d6d2",
  inkButtonText: "#0c1719",
} as const;

// 语义状态色：成功、警告、错误各自一色，警告不借用信息蓝。
const status = {
  success: { light: "#0b7f92", dark: "#3cc6d4" },
  warning: { light: "#8a4a00", dark: "#f0b968" },
  error: { light: "#a8261a", dark: "#ff8f80" },
  info: { light: workbenchTokens.lit, dark: smoke.lit },
} as const;

export function applyWorkbenchTheme() {
  return applyTheme({ theme: { tokens: {
    fontFamilyBase: workbenchTokens.sans,
    fontFamilyHeading: workbenchTokens.sans,
    fontFamilyMonospace: workbenchTokens.mono,
    fontSizeBodyM: "14px", lineHeightBodyM: "22px",
    fontSizeBodyS: "12px", lineHeightBodyS: "18px",
    fontSizeHeadingXl: "24px", lineHeightHeadingXl: "32px", fontWeightHeadingXl: "600", letterSpacingHeadingXl: "0px",
    fontSizeHeadingL: "20px", lineHeightHeadingL: "28px", fontWeightHeadingL: "600", letterSpacingHeadingL: "0px",
    fontSizeHeadingM: "17px", lineHeightHeadingM: "24px", fontWeightHeadingM: "600", letterSpacingHeadingM: "0px",
    fontWeightButton: "500",
    colorTextBodyDefault: { light: workbenchTokens.ink, dark: smoke.ink },
    colorTextHeadingDefault: { light: workbenchTokens.ink, dark: smoke.heading },
    colorTextBodySecondary: { light: workbenchTokens.muted, dark: smoke.muted },
    colorTextFormSecondary: { light: workbenchTokens.muted, dark: smoke.muted },
    colorTextLabel: { light: workbenchTokens.ink, dark: smoke.ink },
    colorTextInteractiveDefault: { light: workbenchTokens.ink, dark: smoke.ink },
    colorTextInteractiveHover: { light: workbenchTokens.lit, dark: smoke.lit },
    colorTextLinkDefault: { light: workbenchTokens.link, dark: smoke.link },
    colorTextLinkHover: { light: workbenchTokens.linkHover, dark: smoke.linkHover },
    colorTextAccent: { light: workbenchTokens.lit, dark: smoke.lit },
    colorBorderItemFocused: { light: workbenchTokens.lit, dark: smoke.lit },
    // 主操作是墨：浅色是深墨底浅字，烟熏里反过来；每个区块只留一个。
    colorBackgroundButtonPrimaryDefault: { light: workbenchTokens.inkButton, dark: smoke.inkButton },
    colorBackgroundButtonPrimaryHover: { light: workbenchTokens.inkButtonHover, dark: smoke.inkButtonHover },
    colorBackgroundButtonPrimaryActive: { light: workbenchTokens.inkButtonActive, dark: smoke.inkButtonActive },
    colorTextButtonPrimaryDefault: { light: workbenchTokens.inkButtonText, dark: smoke.inkButtonText },
    colorTextButtonPrimaryHover: { light: workbenchTokens.inkButtonText, dark: smoke.inkButtonText },
    colorTextButtonPrimaryActive: { light: workbenchTokens.inkButtonText, dark: smoke.inkButtonText },
    // 普通按钮是一小块玻璃：墨色文字、细亮边，悬停时字亮成光色。
    colorTextButtonNormalDefault: { light: workbenchTokens.ink, dark: smoke.ink },
    colorTextButtonNormalHover: { light: workbenchTokens.lit, dark: smoke.lit },
    colorTextButtonNormalActive: { light: workbenchTokens.lit, dark: smoke.lit },
    colorBackgroundButtonNormalDefault: { light: "rgba(255, 255, 255, 0.3)", dark: "rgba(255, 255, 255, 0.05)" },
    colorBackgroundButtonNormalHover: { light: "rgba(255, 255, 255, 0.52)", dark: "rgba(255, 255, 255, 0.09)" },
    colorBackgroundButtonNormalActive: { light: "rgba(255, 255, 255, 0.4)", dark: "rgba(255, 255, 255, 0.07)" },
    colorBorderButtonNormalDefault: { light: "rgba(9, 22, 30, 0.16)", dark: "rgba(214, 232, 227, 0.16)" },
    colorBorderButtonNormalHover: { light: "rgba(9, 22, 30, 0.28)", dark: "rgba(214, 232, 227, 0.3)" },
    colorBorderButtonNormalActive: { light: "rgba(9, 22, 30, 0.34)", dark: "rgba(214, 232, 227, 0.36)" },
    // 不带 href 的 Link 与 Button 的 link 变体：片上的轻动作，光色文字、没有底色。
    colorTextLinkButtonNormalDefault: { light: workbenchTokens.link, dark: smoke.link },
    colorTextLinkButtonNormalHover: { light: workbenchTokens.linkHover, dark: smoke.linkHover },
    colorTextLinkButtonNormalActive: { light: workbenchTokens.linkHover, dark: smoke.linkHover },
    colorBackgroundButtonLinkHover: { light: "rgba(9, 22, 30, 0.05)", dark: "rgba(255, 255, 255, 0.06)" },
    colorBackgroundButtonLinkActive: { light: "rgba(9, 22, 30, 0.08)", dark: "rgba(255, 255, 255, 0.09)" },
    borderWidthButton: "1px",
    // 输入与开关：片上再浅一层，细边，聚焦时才用光色
    colorBackgroundInputDefault: { light: "rgba(255, 255, 255, 0.62)", dark: "rgba(255, 255, 255, 0.045)" },
    colorBackgroundInputDisabled: { light: "rgba(9, 22, 30, 0.04)", dark: "rgba(255, 255, 255, 0.02)" },
    colorBorderInputDefault: { light: "rgba(9, 22, 30, 0.2)", dark: "rgba(214, 232, 227, 0.2)" },
    colorBorderInputFocused: { light: workbenchTokens.lit, dark: smoke.lit },
    colorBorderControlDefault: { light: "rgba(9, 22, 30, 0.34)", dark: "rgba(214, 232, 227, 0.34)" },
    colorBackgroundControlChecked: { light: workbenchTokens.ink, dark: smoke.inkButton },
    colorBackgroundItemSelected: { light: "rgba(24, 70, 196, 0.07)", dark: "rgba(214, 227, 255, 0.1)" },
    colorBorderItemSelected: { light: workbenchTokens.lit, dark: smoke.lit },
    colorTextStatusSuccess: status.success,
    colorTextStatusWarning: status.warning,
    colorTextStatusError: status.error,
    colorTextStatusInfo: status.info,
    // 两个值写法不同是有意的：值相同时 Cloudscape 不会为 dark mode 生成覆盖，默认的深色底会盖住玻璃。
    colorBackgroundLayoutMain: { light: "transparent", dark: "rgba(0, 0, 0, 0)" },
    // Cloudscape 容器没有背景模糊，所以比 --k-plate 更实一些，色相相同。
    colorBackgroundContainerContent: { light: "rgba(244, 249, 248, 0.8)", dark: "rgba(16, 30, 33, 0.82)" },
    // 面板只有一层底：标题区（容器、对话框、表头）不再叠第二层，否则头尾比正文更不透明。
    colorBackgroundContainerHeader: { light: "transparent", dark: "rgba(0, 0, 0, 0)" },
    colorBackgroundPopover: { light: "rgba(243, 248, 247, 0.97)", dark: "rgba(15, 27, 30, 0.96)" },
    colorBackgroundDropdownItemDefault: { light: "rgba(243, 248, 247, 0.97)", dark: "rgba(15, 27, 30, 0.96)" },
    colorBorderContainerTop: { light: workbenchTokens.rule, dark: smoke.rule },
    colorBorderDividerDefault: { light: workbenchTokens.rule, dark: smoke.rule },
    // 表格行分隔是刻在片上的细线
    colorBorderDividerSecondary: { light: "rgba(9, 22, 30, 0.08)", dark: "rgba(214, 232, 227, 0.08)" },
    // 容器与玻璃片同一个圆角（--k-plate-r）
    borderRadiusContainer: "16px", borderRadiusButton: "7px", borderRadiusInput: "7px", borderRadiusDropdown: "9px", borderRadiusAlert: "9px",
    borderRadiusBadge: "20px",
  } } });
}
