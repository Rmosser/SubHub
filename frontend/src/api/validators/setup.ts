import { isRecord } from "./shared";

export interface SetupStatus {
  setup_required: boolean;
  initialized: boolean;
  instance_initialized: boolean;
  access_mode: string;
}

export function parseSetupStatus(raw: unknown): SetupStatus {
  if (!isRecord(raw)
    || typeof raw.setup_required !== "boolean"
    || typeof raw.initialized !== "boolean"
    || typeof raw.instance_initialized !== "boolean"
    || typeof raw.access_mode !== "string"
    || raw.initialized === raw.setup_required) {
    throw new Error("Invalid setup status response");
  }
  return {
    setup_required: raw.setup_required,
    initialized: raw.initialized,
    instance_initialized: raw.instance_initialized,
    access_mode: raw.access_mode,
  };
}
