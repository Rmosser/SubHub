import { useCallback, useEffect, useRef, type ReactNode } from "react";
import Modal, { type ModalProps } from "@cloudscape-design/components/modal";
import { t } from "@/i18n/translations";

// 玻璃对话框：Cloudscape Modal 负责焦点陷阱、Esc、可访问名称与关闭按钮；
// 它被放进我们自己的磨砂层，正文只有一层底，标题刻在面板上，动作在正文末尾（每个对话框一个主按钮）。
// Modal 挂载时就会取根节点，所以磨砂只在对话框打开时出现（data-open）。
interface GlassDialogProps {
  visible: boolean;
  header: string;
  children: ReactNode;
  actions?: ReactNode;
  size?: ModalProps.Size;
  onDismiss: () => void;
}

export function GlassDialog({ visible, header, children, actions, size, onDismiss }: GlassDialogProps) {
  const layerRef = useRef<HTMLElement | null>(null);
  const visibleRef = useRef(visible);
  visibleRef.current = visible;

  const closeLayer = useCallback((layer: HTMLElement | null) => {
    layer?.remove();
    if (layerRef.current === layer) layerRef.current = null;
  }, []);

  // Cloudscape 在根节点就绪前卸载（StrictMode 的二次挂载、快速切页）时只会 abort，不会把这个根交回来，
  // 所以在 abort 时自己收走，否则每次挂载都会在 body 下留下一个空层。
  const openLayer = useCallback(async ({ abortSignal }: { abortSignal: AbortSignal }) => {
    const layer = document.createElement("div");
    layer.className = "glass-dialog-layer";
    layer.dataset.open = String(visibleRef.current);
    document.body.appendChild(layer);
    layerRef.current = layer;
    abortSignal.addEventListener("abort", () => closeLayer(layer), { once: true });
    return layer;
  }, [closeLayer]);

  useEffect(() => {
    if (layerRef.current) layerRef.current.dataset.open = String(visible);
  }, [visible]);

  return (
    <Modal
      visible={visible}
      size={size}
      closeAriaLabel={t("common.close")}
      onDismiss={onDismiss}
      getModalRoot={openLayer}
      removeModalRoot={closeLayer}
      header={<span className="s-dialog-title">{header}</span>}
    >
      {/* Cloudscape 关着的对话框只是 display:none，正文照样渲染；关着时不渲染正文，
          页面挂载就不用替每个没打开的对话框建一整份表单（服务目录的批量分配是每个分类一个下拉）。
          关闭没有退出动画，打开时正文和对话框同一次提交出现，焦点陷阱照常取到第一个可聚焦项。 */}
      {visible ? <div className="s-dialog-body">{children}</div> : null}
      {visible && actions ? <div className="s-dialog-actions">{actions}</div> : null}
    </Modal>
  );
}
