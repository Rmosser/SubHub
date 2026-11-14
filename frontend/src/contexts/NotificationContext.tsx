import React, { createContext, useCallback, useContext, useState } from "react";
import { Flashbar, FlashbarProps } from "@cloudscape-design/components";
import { toast } from "sonner";

type NotificationType = FlashbarProps.Type;

interface NotificationItem extends FlashbarProps.MessageDefinition {
  id: string;
}

interface NotificationContextValue {
  addNotification: (type: NotificationType, content: string) => void;
  addToast: (type: "success" | "error" | "warning" | "info", message: string, description?: string) => void;
  clearNotifications: () => void;
}

const NotificationContext = createContext<NotificationContextValue>({
  addNotification: () => {},
  addToast: () => {},
  clearNotifications: () => {},
});

let nextId = 0;

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<NotificationItem[]>([]);

  const addNotification = useCallback((type: NotificationType, content: string) => {
    const id = String(++nextId);
    const item: NotificationItem = {
      id,
      type,
      content,
      dismissible: true,
      onDismiss: () => {
        setItems((prev) => prev.filter((n) => n.id !== id));
      },
    };
    setItems((prev) => [...prev, item]);
    if (type !== "error") {
      setTimeout(() => {
        setItems((prev) => prev.filter((n) => n.id !== id));
      }, 5000);
    }
  }, []);

  const addToast = useCallback(
    (type: "success" | "error" | "warning" | "info", message: string, description?: string) => {
      const opts = description ? { description } : undefined;
      switch (type) {
        case "success":
          toast.success(message, opts);
          break;
        case "error":
          toast.error(message, opts);
          break;
        case "warning":
          toast.warning(message, opts);
          break;
        case "info":
          toast.info(message, opts);
          break;
      }
    },
    []
  );

  const clearNotifications = useCallback(() => setItems([]), []);

  return (
    <NotificationContext.Provider value={{ addNotification, addToast, clearNotifications }}>
      {children}
      <Flashbar items={items} />
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  return useContext(NotificationContext);
}
