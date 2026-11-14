import type {
  AdaptedTarget,
  CapabilityClientView,
  CapabilityGroup,
  CapabilitySupport,
  GeneralProfile,
  LocalizedText,
  ProfileCapabilitiesResponse,
  ProfileCapability,
  ProfileCapabilitySubfield,
  ProfileEditorCard,
  ProfileEditorCardActivation,
  ProfileEditorDetailSection,
  ProfileEditorFamily,
  ProfileEditorGroup,
  ProfileEditorSchemaResponse,
  ProfileEditorState,
  ScenarioProfile,
  SelectOption,
  SettingSchemaLike,
  SyntaxHint,
} from "@/types";
import {
  anyRecord,
  array,
  bool,
  itemResponse,
  listResponse,
  literal,
  num,
  object,
  optional,
  record,
  response,
  str,
  type Parser,
} from "./schema";
import { isRecord } from "./shared";

const localizedText = object<LocalizedText>({ zh: str, en: str });
// The schema builders send `{}` when a field has no localized text.
const i18n: Parser<LocalizedText | undefined> = (value, path) =>
  isRecord(value) && Object.keys(value).length === 0 ? undefined : optional(localizedText)(value, path);
const fieldType = literal("bool", "string", "int", "list", "dict", "select");
const clientName = literal("surge", "clash", "shadowrocket");

const editorState = object<ProfileEditorState>({
  version: num,
  families: record(str),
  active_client: record(str),
  legacy: bool,
});

const capabilities = optional(record(anyRecord));

const generalProfile = object<GeneralProfile>({
  id: str,
  name: str,
  settings: anyRecord,
  editor_state: editorState,
  capabilities,
  is_system_default: bool,
  legacy: optional(bool),
  updated_at: str,
});

export const scenarioProfile = object<ScenarioProfile>({
  id: str,
  slug: str,
  name: str,
  description: str,
  enabled: bool,
  sort_order: num,
  settings: anyRecord,
  editor_state: editorState,
  capabilities,
  legacy: optional(bool),
  updated_at: str,
});

const selectOption = object<SelectOption>({
  value: str,
  label: str,
  label_i18n: i18n,
  description: optional(str),
  description_i18n: i18n,
});

const support = object<CapabilitySupport>({
  status: literal("supported", "auto_mapped", "downgraded", "unsupported", "pending_validation"),
  reason: str,
  reason_i18n: i18n,
  diagnostic_codes: array(str),
  kind: optional(literal("mirror_missing", "client_missing")),
});

const syntaxHint = object<SyntaxHint>({
  title: str,
  title_i18n: i18n,
  body: str,
  body_i18n: i18n,
  status: optional(str),
});

const clientView = object<CapabilityClientView>({
  key: optional(str),
  label: str,
  label_i18n: i18n,
  type: fieldType,
  description: optional(str),
  description_i18n: i18n,
  placeholder: optional(str),
  placeholder_i18n: i18n,
  rows: optional(num),
  options: optional(array(selectOption)),
  support,
  editing_mode: literal("shared", "standalone", "experimental", "adapted", "unavailable"),
  adapted_hint: optional(str),
  adapted_hint_i18n: i18n,
  adapted_targets: optional(array(object<AdaptedTarget>({ section: str, section_zh: optional(str), kind: str }))),
  syntax_hints: optional(array(syntaxHint)),
});

const subfield = object<ProfileCapabilitySubfield>({
  id: str,
  label: str,
  label_i18n: i18n,
  source_client: clientName,
  description: optional(str),
  description_i18n: i18n,
  clients: object<ProfileCapabilitySubfield["clients"]>({ surge: clientView, clash: clientView, shadowrocket: clientView }),
});

const capability = object<ProfileCapability>({
  id: str,
  title: str,
  title_i18n: i18n,
  description: optional(str),
  description_i18n: i18n,
  subfields: array(subfield),
});

const capabilityGroup = object<CapabilityGroup>({
  id: str,
  title: str,
  title_i18n: i18n,
  description: optional(str),
  description_i18n: i18n,
  capabilities: array(capability),
});

const settingSchema = object<SettingSchemaLike>({
  key: str,
  label: str,
  label_i18n: i18n,
  type: fieldType,
  description: optional(str),
  description_i18n: i18n,
  placeholder: optional(str),
  placeholder_i18n: i18n,
  rows: optional(num),
  options: optional(array(selectOption)),
});

const detailSection = object<ProfileEditorDetailSection>({
  kind: str,
  title: str,
  title_i18n: i18n,
  body: str,
  body_i18n: i18n,
  status: optional(str),
});

const card = object<ProfileEditorCard>({
  id: str,
  family_id: str,
  group_id: str,
  title: str,
  title_i18n: i18n,
  description: str,
  description_i18n: i18n,
  mode_kind: literal("shared", "client_native", "experimental", "unsupported", "generated_info"),
  status_badge: literal("stable", "limited", "experimental", "unsupported", "generated"),
  client: optional(clientName),
  field_keys: array(str),
  input_schema: array(settingSchema),
  detail_sections: array(detailSection),
  activation: optional(
    object<ProfileEditorCardActivation>({ family_id: str, mode: str, client: optional(str) }),
  ),
});

const editorGroup = object<ProfileEditorGroup>({
  id: str,
  title: str,
  title_i18n: i18n,
  description: optional(str),
  description_i18n: i18n,
});

const family = object<ProfileEditorFamily>({
  id: str,
  group_id: str,
  title: str,
  title_i18n: i18n,
  mode_label: optional(str),
  mode_label_i18n: i18n,
  mode_ids: array(str),
  default_mode: str,
});

export const parseGeneralProfileItem = itemResponse(generalProfile);
export const parseGeneralProfileList = listResponse(generalProfile);
export const parseScenarioProfileList = listResponse(scenarioProfile);

export const parseProfileCapabilities = response(
  object<ProfileCapabilitiesResponse>({
    ok: bool,
    groups: array(capabilityGroup),
    clients: optional(array(str)),
    expert_field_keys: array(str),
  }),
);

export const parseProfileEditorSchema = response(
  object<ProfileEditorSchemaResponse>({
    ok: bool,
    groups: array(editorGroup),
    families: array(family),
    cards: array(card),
    default_mode: record(str),
    detail_sections: anyRecord,
    legacy_handling: object<ProfileEditorSchemaResponse["legacy_handling"]>({
      title: str,
      title_i18n: i18n,
      message: str,
      message_i18n: i18n,
      action_label: str,
      action_label_i18n: i18n,
    }),
  }),
);

