from __future__ import annotations

import json
from typing import Any

from app.models import DiffResult


class ProfileDiffer:
    @staticmethod
    def diff(
        primary_settings: dict[str, Any],
        target_settings: dict[str, Any],
    ) -> list[DiffResult]:
        all_keys = sorted(set(primary_settings) | set(target_settings))
        results: list[DiffResult] = []
        for key in all_keys:
            in_primary = key in primary_settings
            in_target = key in target_settings
            if in_primary and not in_target:
                results.append(
                    DiffResult(
                        key=key,
                        diff_type="removed",
                        primary_value=primary_settings[key],
                        target_value=None,
                    )
                )
            elif in_target and not in_primary:
                results.append(
                    DiffResult(
                        key=key,
                        diff_type="added",
                        primary_value=None,
                        target_value=target_settings[key],
                    )
                )
            else:
                pv = primary_settings[key]
                tv = target_settings[key]
                if not ProfileDiffer._values_equal(pv, tv):
                    results.append(
                        DiffResult(
                            key=key,
                            diff_type="changed",
                            primary_value=pv,
                            target_value=tv,
                        )
                    )
        return results

    @staticmethod
    def _values_equal(a: Any, b: Any) -> bool:
        if isinstance(a, list) and isinstance(b, list):
            return sorted(str(item) for item in a) == sorted(str(item) for item in b)
        if isinstance(a, dict) and isinstance(b, dict):
            return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        return a == b
