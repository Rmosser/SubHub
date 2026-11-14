import type { PolicyRestorePreview } from "@/types";

export function canApplyRestore(
  preview: PolicyRestorePreview | undefined,
  requestRef: string | null,
  currentRef: string,
  busy: boolean,
): boolean {
  return Boolean(preview?.ok && preview.snapshot_digest?.trim() && requestRef !== null && requestRef === currentRef.trim() && !busy);
}
