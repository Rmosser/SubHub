from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from app.config import Settings
from app.models import DiffResult, ReviewAnnotation
from app.services.lazycat_profile import normalize_lazycat_profile_settings
from app.services.profile_differ import ProfileDiffer
from app.storage.sqlite_repo import SqliteRepo

_SYSTEM_PROMPT = (
    "你是一位代理配置专家，精通 Clash/mihomo、Surge、Shadowrocket 配置语义。\n"
    "用户会给你两个配置 profile 的差异列表，请你为每一条差异输出一句简短的中文解释，"
    "说明该差异对代理行为的影响。\n"
    "以 JSON 数组格式回复，每个元素包含 key 和 explanation 两个字段。"
)

_USER_PROMPT_TEMPLATE = (
    "Primary Profile: {primary_name}\n"
    "Target Profile: {target_name}\n\n"
    "差异列表:\n{diff_text}\n\n"
    "请为每一条差异输出 JSON 数组 [{{"
    '"key": "配置项名", "explanation": "影响说明"'
    "}}]"
)


def _json_serialize(value: Any) -> str:
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _build_cache_key(
    primary_id: str,
    primary_updated_at: str,
    target_id: str,
    target_updated_at: str,
) -> str:
    raw = f"{primary_id}|{primary_updated_at}|{target_id}|{target_updated_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _format_diff_text(diffs: list[DiffResult]) -> str:
    lines: list[str] = []
    for diff in diffs:
        pv = _json_serialize(diff.primary_value)
        tv = _json_serialize(diff.target_value)
        lines.append(f"- [{diff.diff_type}] {diff.key}: primary={pv}, target={tv}")
    return "\n".join(lines)


class ReviewService:
    def __init__(self, settings: Settings, repo: SqliteRepo):
        self.settings = settings
        self.repo = repo

    async def review(
        self,
        primary_profile_id: str,
        target_profile_id: str,
    ) -> dict[str, Any]:
        primary = self.repo.get_general_profile(primary_profile_id)
        if not primary:
            raise ValueError(f"primary profile not found: {primary_profile_id}")

        target = self.repo.get_general_profile(target_profile_id)
        if not target:
            raise ValueError(f"target profile not found: {target_profile_id}")

        primary_settings = normalize_lazycat_profile_settings(primary.settings or {})
        target_settings = normalize_lazycat_profile_settings(target.settings or {})

        diffs = ProfileDiffer.diff(primary_settings, target_settings)
        if not diffs:
            return {
                "target_profile_id": target.id,
                "target_profile_name": target.name,
                "annotations": [],
                "cached": False,
            }

        cache_key = _build_cache_key(
            primary.id, primary.updated_at,
            target.id, target.updated_at,
        )

        cached_json = self.repo.load_review_cache(cache_key)
        if cached_json:
            annotations = json.loads(cached_json)
            return {
                "target_profile_id": target.id,
                "target_profile_name": target.name,
                "annotations": annotations,
                "cached": True,
            }

        annotations = await self._call_llm(diffs, primary.name, target.name)

        enriched: list[dict[str, Any]] = []
        explanation_map = {item["key"]: item["explanation"] for item in annotations}
        for diff in diffs:
            enriched.append(
                ReviewAnnotation(
                    key=diff.key,
                    diff_type=diff.diff_type,
                    primary_value=_json_serialize(diff.primary_value),
                    target_value=_json_serialize(diff.target_value),
                    explanation=explanation_map.get(diff.key, ""),
                ).to_dict()
            )

        self.repo.save_review_cache(
            cache_key=cache_key,
            primary_profile_id=primary.id,
            target_profile_id=target.id,
            annotations_json=json.dumps(enriched, ensure_ascii=False),
            primary_updated_at=primary.updated_at,
            target_updated_at=target.updated_at,
        )

        return {
            "target_profile_id": target.id,
            "target_profile_name": target.name,
            "annotations": enriched,
            "cached": False,
        }

    async def _call_llm(
        self,
        diffs: list[DiffResult],
        primary_name: str,
        target_name: str,
    ) -> list[dict[str, str]]:
        api_key = self.repo.get_runtime_setting("review.gemini_api_key") or self.settings.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        model = self.repo.get_runtime_setting("review.review_model") or self.settings.review_model
        diff_text = _format_diff_text(diffs)
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            primary_name=primary_name,
            target_name=target_name,
            diff_text=diff_text,
        )

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 2000,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"content-type": "application/json"},
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()

        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            parsed = [parsed]
        return [
            {"key": str(item.get("key", "")), "explanation": str(item.get("explanation", ""))}
            for item in parsed
            if isinstance(item, dict)
        ]
