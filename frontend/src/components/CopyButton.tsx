import { useState } from "react";
import { Button, ButtonProps } from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { IconButton } from "@/components/InlineAction";

interface CopyButtonProps {
  text: string;
  label?: string;
  variant?: ButtonProps["variant"];
}

export function CopyButton({ text, label = "Copy", variant = "icon" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const { t, locale } = useLocale();
  const { addToast } = useNotifications();
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      addToast("error", t("toast.copy_error"), error instanceof Error ? error.message : undefined);
    }
  };
  const feedback = locale === "zh-CN" ? "已复制" : "Copied";
  // Keep the button node stable so copying preserves keyboard focus.
  // The icon variant gets the 44px touch target on narrow or touch screens (see IconButton).
  return <span className="workbench-copy-control">
    {variant === "icon" ? (
      <IconButton iconName={copied ? "status-positive" : "copy"} onClick={handleCopy} ariaLabel={copied ? feedback : label} />
    ) : (
      <Button variant={variant} iconName={copied ? "status-positive" : "copy"} onClick={handleCopy} ariaLabel={copied ? feedback : label}>
        {copied ? feedback : label}
      </Button>
    )}
    <span className="workbench-sr-only" role="status">{copied ? feedback : ""}</span>
  </span>;
}
