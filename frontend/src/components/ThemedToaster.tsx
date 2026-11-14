import { Toaster } from "sonner";
import { useEffectiveDark } from "@/theme/glassTheme";

// 提示是贴在玻璃顶层的一小片磨砂；状态只染图标，不铺饱和底色。
export function ThemedToaster() {
  const dark = useEffectiveDark();
  return <Toaster position="bottom-right" duration={4000} closeButton theme={dark ? "dark" : "light"} />;
}
