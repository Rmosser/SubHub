#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mark_expr="(unit or repo or service or api) and not slow"
base_ref="${SUBHUB_TEST_BASE_REF:-origin/main}"
if ! git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
  base_ref="main"
fi

changed_tests=()
collect_changed_tests() {
  local path
  while IFS= read -r path; do
    [[ -n "$path" && -f "$path" ]] || continue
    changed_tests+=("$path")
  done
}

if git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
  merge_base="$(git merge-base HEAD "$base_ref")"
  collect_changed_tests < <(git diff --name-only "$merge_base"...HEAD -- 'tests/test_*.py')
fi

collect_changed_tests < <(git diff --name-only --cached -- 'tests/test_*.py')
collect_changed_tests < <(git diff --name-only -- 'tests/test_*.py')
collect_changed_tests < <(git ls-files --others --exclude-standard -- 'tests/test_*.py')

if [[ ${#changed_tests[@]} -gt 0 ]]; then
  unique_changed_tests=()
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    unique_changed_tests+=("$path")
  done < <(printf '%s\n' "${changed_tests[@]}" | sort -u)
  changed_tests=("${unique_changed_tests[@]}")
fi

if [[ ${#changed_tests[@]} -gt 0 ]]; then
  ./.venv/bin/python -m pytest -m "$mark_expr" "${changed_tests[@]}" "$@"
else
  ./.venv/bin/python -m pytest -m "$mark_expr" "$@"
fi
