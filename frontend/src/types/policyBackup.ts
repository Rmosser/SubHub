export interface PolicyBackupStatus {
  enabled: boolean;
  configured: boolean;
  repo_url: string;
  branch: string;
  subdir: string;
  dirty: boolean;
  syncing: boolean;
  last_result: string;
  last_sync_at: string;
  last_commit_sha: string;
  last_error: string;
}

export interface PolicyRestorePreviewSection {
  name: string;
  added: string[];
  removed: string[];
  changed: string[];
  added_count: number;
  removed_count: number;
  changed_count: number;
}

export interface PolicyRestorePreview {
  ok: boolean;
  ref: string;
  source_digest: string;
  snapshot_digest: string;
  changed: boolean;
  sections: PolicyRestorePreviewSection[];
}

export interface PolicyBackupSyncResult {
  ok: boolean;
  busy?: boolean;
  changed?: boolean;
  commit_sha?: string;
  reasons?: string[];
  error?: string;
  dirty?: boolean;
}

export interface PolicyBackupApplyResult {
  ok: boolean;
  preview: PolicyRestorePreview;
  applied: {
    manual_categories: number;
    global_custom_rules: number;
    scenario_count: number;
  };
}

export interface PolicyBackupSnapshot {
  manifest: Record<string, unknown>;
  global: {
    custom_rules: Record<string, unknown>[];
  };
  categories: {
    manual_categories: Record<string, unknown>[];
  };
  scenarios: Record<string, Record<string, unknown>>;
}
