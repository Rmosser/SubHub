import { FormField, Input, Select, Toggle, Textarea, SpaceBetween } from "@cloudscape-design/components";
import { useEffect, useId, useState } from "react";
import { parseJsonObject } from "@/api/validators/json";
import { useLocale } from "@/contexts/LocaleContext";
import { t as translate } from "@/i18n/translations";
import { integerDraftValue, settingError } from "./settingsValidation";

export interface SettingOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

export type SettingType = "bool" | "string" | "int" | "list" | "dict" | "select";

export interface SettingSchema {
  key: string;
  label: string;
  type: SettingType;
  description?: string;
  /** 取值范围等约束：显示在输入框下方，输入后仍可见 */
  constraint?: string;
  placeholder?: string;
  rows?: number;
  options?: SettingOption[];
}

interface SettingsFormProps {
  schema: SettingSchema[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled?: boolean;
}

export function SettingsForm({ schema, values, onChange, disabled = false }: SettingsFormProps) {
  return (
    <SpaceBetween size="l">
      {schema.map((field) => (
        <SettingField
          key={field.key}
          field={field}
          value={values[field.key]}
          onChange={(v) => onChange(field.key, v)}
          disabled={disabled}
        />
      ))}
    </SpaceBetween>
  );
}

interface SettingFieldProps {
  field: SettingSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}

export function SettingField({ field, value, onChange, disabled = false }: SettingFieldProps) {
  const { t } = useLocale();
  // Cloudscape Toggle 不读 FormField 的 controlId：两边显式用同一个 id，<label for> 才指向开关本身
  const controlId = useId();
  if (field.type === "dict") {
    return <DictSettingField field={field} value={value} onChange={onChange} disabled={disabled} />;
  }

  return (
    <div style={{ width: "100%" }}>
      <FormField controlId={controlId} label={field.label} description={field.description} constraintText={field.constraint} errorText={settingError(field.type, value) ? t(settingError(field.type, value)!) : undefined}>
        {renderField(field, value, onChange, disabled, controlId)}
      </FormField>
    </div>
  );
}

function stringifyDictValue(value: unknown): string {
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  const text = String(value ?? "").trim();
  return text || "{}";
}

function DictSettingField({ field, value, onChange, disabled = false }: SettingFieldProps) {
  const { t } = useLocale();
  const committedText = stringifyDictValue(value);
  const [draftValue, setDraftValue] = useState(committedText);
  const [lastCommittedText, setLastCommittedText] = useState(committedText);
  const error = settingError("dict", value);

  useEffect(() => {
    if (committedText !== lastCommittedText) {
      setDraftValue(committedText);
      setLastCommittedText(committedText);
    }
  }, [committedText, lastCommittedText]);

  return (
    <div style={{ width: "100%" }}>
      <FormField label={field.label} description={field.description} constraintText={field.constraint} errorText={error ? t(error) : undefined}>
        <Textarea
          value={draftValue}
          onChange={({ detail }) => {
            const nextValue = detail.value;
            setDraftValue(nextValue);
            try {
              const parsed = parseJsonObject(nextValue);
              onChange(parsed);
              setLastCommittedText(JSON.stringify(parsed, null, 2));
            } catch {
              // Preserve invalid text in the parent draft so saving can be blocked.
              onChange(nextValue);
              setLastCommittedText(stringifyDictValue(nextValue));
            }
          }}
          rows={field.rows ?? 6}
          disabled={disabled}
          placeholder={field.placeholder ?? '{"key": "value"}'}
        />
      </FormField>
    </div>
  );
}

function renderField(field: SettingSchema, value: unknown, onChange: (v: unknown) => void, disabled: boolean, controlId: string) {
  switch (field.type) {
    case "bool":
      return (
        <Toggle controlId={controlId} checked={!!value} onChange={({ detail }) => onChange(detail.checked)} disabled={disabled} />
      );
    case "int":
      return (
        <Input
          type="number"
          value={String(value ?? "")}
          onChange={({ detail }) => onChange(integerDraftValue(detail.value))}
          disabled={disabled}
          placeholder={field.placeholder}
        />
      );
    case "list":
      return (
        <Textarea
          value={Array.isArray(value) ? value.join("\n") : String(value ?? "")}
          onChange={({ detail }) =>
            onChange(detail.value.split("\n").filter((line) => line.trim() !== ""))
          }
          rows={field.rows ?? 5}
          disabled={disabled}
          placeholder={field.placeholder ?? translate("settings.one_per_line")}
        />
      );
    case "select": {
      const normalizedValue = typeof value === "string" ? value : String(value ?? "").trim();
      const knownOptions = field.options ?? [];
      const selectedOption = knownOptions.find((option) => option.value === normalizedValue);
      const customOption = normalizedValue && !selectedOption
        ? {
          value: normalizedValue,
          label: translate("settings.unlisted_value", { value: normalizedValue }),
          description: translate("settings.unlisted_value_hint"),
        }
        : null;
      const options = customOption ? [customOption, ...knownOptions] : knownOptions;
      return (
        <Select
          selectedOption={selectedOption || customOption}
          options={options}
          onChange={({ detail }) => onChange(detail.selectedOption.value ?? "")}
          disabled={disabled}
          placeholder={field.placeholder}
        />
      );
    }
    default:
      return (
        <Input
          value={String(value ?? "")}
          onChange={({ detail }) => onChange(detail.value)}
          disabled={disabled}
          placeholder={field.placeholder}
        />
      );
  }
}
