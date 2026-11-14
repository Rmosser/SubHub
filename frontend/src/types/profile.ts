export type ClientSupportState =
  | "supported"
  | "auto_mapped"
  | "downgraded"
  | "unsupported"
  | "pending_validation";

export type CapabilitySupportKind =
  | "mirror_missing"
  | "client_missing";

export type CapabilityEditingMode =
  | "shared"
  | "standalone"
  | "experimental"
  | "adapted"
  | "unavailable";

export interface LocalizedText {
  zh: string;
  en: string;
}

export interface SelectOption {
  value: string;
  label: string;
  label_i18n?: LocalizedText;
  description?: string;
  description_i18n?: LocalizedText;
}

export interface CapabilitySupport {
  status: ClientSupportState;
  reason: string;
  reason_i18n?: LocalizedText;
  diagnostic_codes: string[];
  kind?: CapabilitySupportKind | null;
}

export interface AdaptedTarget {
  section: string;
  section_zh?: string;
  kind: string;
}

export interface SyntaxHint {
  title: string;
  title_i18n?: LocalizedText;
  body: string;
  body_i18n?: LocalizedText;
  status?: string;
}

export interface CapabilityClientView {
  key?: string;
  label: string;
  label_i18n?: LocalizedText;
  type: "bool" | "string" | "int" | "list" | "dict" | "select";
  description?: string;
  description_i18n?: LocalizedText;
  placeholder?: string;
  placeholder_i18n?: LocalizedText;
  rows?: number;
  options?: SelectOption[];
  support: CapabilitySupport;
  editing_mode: CapabilityEditingMode;
  adapted_hint?: string;
  adapted_hint_i18n?: LocalizedText;
  adapted_targets?: AdaptedTarget[];
  syntax_hints?: SyntaxHint[];
}

export interface ProfileCapabilitySubfield {
  id: string;
  label: string;
  label_i18n?: LocalizedText;
  source_client: "surge" | "clash" | "shadowrocket";
  description?: string;
  description_i18n?: LocalizedText;
  clients: Record<"surge" | "clash" | "shadowrocket", CapabilityClientView>;
}

export interface ProfileCapability {
  id: string;
  title: string;
  title_i18n?: LocalizedText;
  description?: string;
  description_i18n?: LocalizedText;
  subfields: ProfileCapabilitySubfield[];
}

export interface CapabilityGroup {
  id: string;
  title: string;
  title_i18n?: LocalizedText;
  description?: string;
  description_i18n?: LocalizedText;
  capabilities: ProfileCapability[];
}

export interface ProfileCapabilitiesResponse {
  ok: boolean;
  groups: CapabilityGroup[];
  clients?: string[];
  expert_field_keys: string[];
}

export interface ProfileEditorState {
  version: number;
  families: Record<string, string>;
  active_client: Record<string, string>;
  legacy: boolean;
}

export interface ProfileEditorDetailSection {
  kind: string;
  title: string;
  title_i18n?: LocalizedText;
  body: string;
  body_i18n?: LocalizedText;
  status?: string;
}

export interface ProfileEditorCardActivation {
  family_id: string;
  mode: string;
  client?: string | null;
}

export interface ProfileEditorCard {
  id: string;
  family_id: string;
  group_id: string;
  title: string;
  title_i18n?: LocalizedText;
  description: string;
  description_i18n?: LocalizedText;
  mode_kind: "shared" | "client_native" | "experimental" | "unsupported" | "generated_info";
  status_badge: "stable" | "limited" | "experimental" | "unsupported" | "generated";
  client?: "surge" | "clash" | "shadowrocket" | null;
  field_keys: string[];
  input_schema: SettingSchemaLike[];
  detail_sections: ProfileEditorDetailSection[];
  activation?: ProfileEditorCardActivation | null;
}

export interface ProfileEditorGroup {
  id: string;
  title: string;
  title_i18n?: LocalizedText;
  description?: string;
  description_i18n?: LocalizedText;
}

export interface ProfileEditorFamily {
  id: string;
  group_id: string;
  title: string;
  title_i18n?: LocalizedText;
  mode_label?: string;
  mode_label_i18n?: LocalizedText;
  mode_ids: string[];
  default_mode: string;
}

export interface ProfileEditorSchemaResponse {
  ok: boolean;
  groups: ProfileEditorGroup[];
  families: ProfileEditorFamily[];
  cards: ProfileEditorCard[];
  default_mode: Record<string, string>;
  detail_sections: Record<string, unknown>;
  legacy_handling: {
    title: string;
    title_i18n?: LocalizedText;
    message: string;
    message_i18n?: LocalizedText;
    action_label: string;
    action_label_i18n?: LocalizedText;
  };
}

export interface SettingSchemaLike {
  key: string;
  label: string;
  label_i18n?: LocalizedText;
  type: "bool" | "string" | "int" | "list" | "dict" | "select";
  description?: string;
  description_i18n?: LocalizedText;
  placeholder?: string;
  placeholder_i18n?: LocalizedText;
  rows?: number;
  options?: SelectOption[];
}

export interface GeneralProfile {
  id: string;
  name: string;
  settings: Record<string, unknown>;
  editor_state: ProfileEditorState;
  capabilities?: Record<string, Record<string, unknown>>;
  is_system_default: boolean;
  legacy?: boolean;
  updated_at: string;
}

export interface ScenarioProfile {
  id: string;
  slug: string;
  name: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  settings: Record<string, unknown>;
  editor_state: ProfileEditorState;
  capabilities?: Record<string, Record<string, unknown>>;
  legacy?: boolean;
  updated_at: string;
}
