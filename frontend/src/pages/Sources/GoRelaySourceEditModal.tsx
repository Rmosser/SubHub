import { useState, useEffect } from "react";
import { FormField, Input, Toggle, SpaceBetween } from "@cloudscape-design/components";
import { FormModal } from "@/components/FormModal";
import { useLocale } from "@/contexts/LocaleContext";
import type { GoRelaySource } from "@/types";

const MASKED_PASSWORD = "••••••••";

interface GoRelaySourceEditModalProps {
  visible: boolean;
  source: GoRelaySource | null;
  loading: boolean;
  onSave: (data: Record<string, unknown>) => void;
  onCancel: () => void;
}

export function GoRelaySourceEditModal({
  visible,
  source,
  loading,
  onSave,
  onCancel,
}: GoRelaySourceEditModalProps) {
  const { t } = useLocale();
  const isEdit = !!source;

  const [name, setName] = useState("");
  const [loginUrl, setLoginUrl] = useState("");
  const [gorelayUsername, setGorelayUsername] = useState("");
  const [gorelayPassword, setGorelayPassword] = useState("");
  const [gorelayPasswordDirty, setGorelayPasswordDirty] = useState(false);
  const [proxyUsername, setProxyUsername] = useState("");
  const [proxyPassword, setProxyPassword] = useState("");
  const [proxyPasswordDirty, setProxyPasswordDirty] = useState(false);
  const [selectorsJson, setSelectorsJson] = useState("{}");
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (source) {
      setName(source.name);
      setLoginUrl(source.login_url);
      setGorelayUsername(source.gorelay_username);
      setGorelayPassword(source.has_gorelay_password ? MASKED_PASSWORD : "");
      setGorelayPasswordDirty(false);
      setProxyUsername(source.proxy_username);
      setProxyPassword(source.has_proxy_password ? MASKED_PASSWORD : "");
      setProxyPasswordDirty(false);
      setSelectorsJson(source.selectors_json || "{}");
      setEnabled(source.enabled);
    } else {
      setName("");
      setLoginUrl("");
      setGorelayUsername("");
      setGorelayPassword("");
      setGorelayPasswordDirty(false);
      setProxyUsername("");
      setProxyPassword("");
      setProxyPasswordDirty(false);
      setSelectorsJson("{}");
      setEnabled(true);
    }
  }, [source, visible]);

  const handleMaskedPasswordFocus = (
    value: string,
    dirty: boolean,
    setValue: (nextValue: string) => void,
  ) => {
    if (!dirty && value === MASKED_PASSWORD) {
      setValue("");
    }
  };

  const handleSubmit = () => {
    const body: Record<string, unknown> = {
      name,
      login_url: loginUrl,
      gorelay_username: gorelayUsername,
      selectors_json: selectorsJson,
      enabled,
    };
    if (gorelayPasswordDirty && gorelayPassword) body.gorelay_password = gorelayPassword;
    if (proxyUsername) body.proxy_username = proxyUsername;
    if (proxyPasswordDirty && proxyPassword) body.proxy_password = proxyPassword;
    if (isEdit) body.id = source!.id;
    onSave(body);
  };

  return (
    <FormModal
      visible={visible}
      header={isEdit ? t("sources.edit_gorelay") : t("sources.add_gorelay")}
      loading={loading}
      confirmLabel={t("common.save")}
      onSubmit={handleSubmit}
      onCancel={onCancel}
    >
      <SpaceBetween size="l">
        <FormField label={t("common.name")}>
          <Input value={name} onChange={({ detail }) => setName(detail.value)} />
        </FormField>
        <FormField label={t("sources.login_url")}>
          <Input value={loginUrl} onChange={({ detail }) => setLoginUrl(detail.value)} type="url" />
        </FormField>
        <FormField label={t("sources.gorelay_username")}>
          <Input value={gorelayUsername} onChange={({ detail }) => setGorelayUsername(detail.value)} />
        </FormField>
        <FormField label={t("sources.gorelay_password")}>
          <Input
            value={gorelayPassword}
            placeholder={isEdit ? t("sources.password_replace_hint") : undefined}
            onFocus={() => handleMaskedPasswordFocus(gorelayPassword, gorelayPasswordDirty, setGorelayPassword)}
            onChange={({ detail }) => {
              setGorelayPasswordDirty(true);
              setGorelayPassword(detail.value);
            }}
            type="password"
          />
        </FormField>
        <FormField label={t("sources.proxy_username")}>
          <Input value={proxyUsername} onChange={({ detail }) => setProxyUsername(detail.value)} />
        </FormField>
        <FormField label={t("sources.proxy_password")}>
          <Input
            value={proxyPassword}
            placeholder={isEdit ? t("sources.password_replace_hint") : undefined}
            onFocus={() => handleMaskedPasswordFocus(proxyPassword, proxyPasswordDirty, setProxyPassword)}
            onChange={({ detail }) => {
              setProxyPasswordDirty(true);
              setProxyPassword(detail.value);
            }}
            type="password"
          />
        </FormField>
        <FormField label={t("common.enabled")}>
          <Toggle checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)} />
        </FormField>
      </SpaceBetween>
    </FormModal>
  );
}
