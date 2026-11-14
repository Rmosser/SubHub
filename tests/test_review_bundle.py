from __future__ import annotations

import io
import zipfile

import pytest

from app.models import NodeRecord, QUALITY_HIGH_PREMIUM, QUALITY_HIGH_STANDARD, QUALITY_MEDIUM
from app.services.review_bundle import (
    ReviewBundleError,
    build_surge_review_bundle,
    validate_reviewer_base_url,
    write_surge_review_bundle,
)
from app.services.subscription_builder import build_surge_config


def _sample_surge_config(managed_url: str) -> str:
    nodes = [
        NodeRecord(
            name="美国联通 premium",
            host="premium.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_PREMIUM,
        ),
        NodeRecord(
            name="standard",
            host="standard.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_STANDARD,
        ),
        NodeRecord(
            name="medium",
            host="medium.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
        "DOMAIN-KEYWORD,taobao,中等质量",
        "IP-CIDR,100.24.211.130/32,中等质量",
    ]
    main_conf, skipped = build_surge_config(nodes, rules, managed_url, profile="lazycat")
    assert skipped == []
    return main_conf


def _sample_surge_overlay_config(managed_url: str, include_url: str) -> str:
    return "\n".join(
        [
            f"#!MANAGED-CONFIG {managed_url} interval=1800 strict=false",
            f"#!include {include_url}",
            "#!MACOS-ONLY",
            "",
            "# SubHub Mac Overlay",
            "",
        ]
    )


def test_validate_reviewer_base_url_rejects_private_hosts() -> None:
    with pytest.raises(ReviewBundleError, match="localhost"):
        validate_reviewer_base_url("http://localhost:8080")
    with pytest.raises(ReviewBundleError, match="private"):
        validate_reviewer_base_url("http://127.0.0.1:8080")
    with pytest.raises(ReviewBundleError, match="private"):
        validate_reviewer_base_url("http://192.168.1.2:8080")


def test_build_surge_review_bundle_exports_expected_zip_layout() -> None:
    main_conf = _sample_surge_config("https://review.example.com/sub/device/t1/surge.conf?profile=lazycat")
    overlay_conf = _sample_surge_overlay_config(
        "https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        "https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
    )
    artifacts = build_surge_review_bundle(
        main_conf,
        source_url="https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is True
    assert "Main config source: https://review.example.com/sub/device/t1/surge.conf?profile=lazycat" in artifacts.references_txt
    assert "Overlay source: https://review.example.com/sub/device/t1/surge-mac-overlay.conf" in artifacts.references_txt
    assert "Git commit: abc123" in artifacts.references_txt
    assert "Review gate: pass" in artifacts.references_txt
    assert "美国联通 premium" in artifacts.unicom_hits_txt

    with zipfile.ZipFile(io.BytesIO(artifacts.zip_bytes)) as archive:
        assert sorted(archive.namelist()) == [
            "surge/lzcbox-surge-mac-overlay.conf",
            "surge/lzcbox-surge.conf",
            "surge/references.txt",
            "surge/unicom-hits.txt",
            "surge/联通命中.txt",
        ]
        assert archive.read("surge/references.txt").decode("utf-8") == artifacts.references_txt
        assert archive.read("surge/lzcbox-surge-mac-overlay.conf").decode("utf-8") == overlay_conf


def test_write_surge_review_bundle_rejects_localhost_managed_config(tmp_path) -> None:
    main_conf = _sample_surge_config("http://127.0.0.1:18080/sub/device/t1/surge.conf?profile=lazycat")
    overlay_conf = _sample_surge_overlay_config(
        "https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        "http://127.0.0.1:18080/sub/device/t1/surge.conf?profile=lazycat",
    )
    artifacts = build_surge_review_bundle(
        main_conf,
        source_url="http://127.0.0.1:18080/sub/device/t1/surge.conf?profile=lazycat",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is False
    with pytest.raises(ReviewBundleError, match="managed config self-reference"):
        write_surge_review_bundle(artifacts, tmp_path / "surge.zip", require_review_ready=True)


def test_write_surge_review_bundle_rejects_missing_dns_failed(tmp_path) -> None:
    main_conf = _sample_surge_config("https://review.example.com/sub/device/t1/surge.conf?profile=lazycat")
    broken_conf = main_conf.replace("FINAL,兜底代理,dns-failed", "FINAL,兜底代理", 1)
    overlay_conf = _sample_surge_overlay_config(
        "https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        "https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
    )
    artifacts = build_surge_review_bundle(
        broken_conf,
        source_url="https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is False
    with pytest.raises(ReviewBundleError, match="FINAL rule must be"):
        write_surge_review_bundle(artifacts, tmp_path / "surge.zip", require_review_ready=True)


def test_write_surge_review_bundle_rejects_unquoted_spaced_requirement_expression(tmp_path) -> None:
    main_conf = _sample_surge_config("https://review.example.com/sub/device/t1/surge.conf?profile=lazycat")
    broken_conf = (
        main_conf.replace("CORE_VERSION>=22", "CORE_VERSION >= 22", 1)
        .replace("CORE_VERSION<22", "CORE_VERSION < 22", 1)
    )
    overlay_conf = _sample_surge_overlay_config(
        "https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        "https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
    )
    artifacts = build_surge_review_bundle(
        broken_conf,
        source_url="https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is False
    assert any(
        "unquoted spaced #!REQUIREMENT expression" in failure
        for failure in artifacts.summary.review_gate_failures
    )
    with pytest.raises(ReviewBundleError, match="unquoted spaced #!REQUIREMENT expression"):
        write_surge_review_bundle(artifacts, tmp_path / "surge.zip", require_review_ready=True)


def test_write_surge_review_bundle_rejects_smart_group_nested_policy_group(tmp_path) -> None:
    main_conf = "\n".join(
        [
            "#!MANAGED-CONFIG https://review.example.com/sub/device/t1/surge.conf interval=1800 strict=false",
            "[Proxy Group]",
            "中等质量 = fallback, p1, url=https://cp.cloudflare.com/generate_204, interval=300",
            "中等质量·日本 = smart, jp-1",
            "中等质量·国际最优 = smart, 中等质量·日本",
            "",
            "[Rule]",
            "FINAL,兜底代理,dns-failed",
            "",
        ]
    )
    overlay_conf = _sample_surge_overlay_config(
        "https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        "https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
    )
    artifacts = build_surge_review_bundle(
        main_conf,
        source_url="https://review.example.com/sub/device/t1/surge.conf",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is False
    assert any("smart group 中等质量·国际最优 nests policy group 中等质量·日本" in failure for failure in artifacts.summary.review_gate_failures)
    with pytest.raises(ReviewBundleError, match="nests policy group"):
        write_surge_review_bundle(artifacts, tmp_path / "surge.zip", require_review_ready=True)


def test_write_surge_review_bundle_rejects_smart_group_include_other_group(tmp_path) -> None:
    main_conf = "\n".join(
        [
            "#!MANAGED-CONFIG https://review.example.com/sub/device/t1/surge.conf interval=1800 strict=false",
            "[Proxy Group]",
            '#!REQUIREMENT CORE_VERSION>=22 中等质量·国际最优 = smart, include-other-group="中等质量·日本, 中等质量·其他"',
            "",
            "[Rule]",
            "FINAL,兜底代理,dns-failed",
            "",
        ]
    )
    overlay_conf = _sample_surge_overlay_config(
        "https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        "https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
    )
    artifacts = build_surge_review_bundle(
        main_conf,
        source_url="https://review.example.com/sub/device/t1/surge.conf",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is False
    assert any("uses include-other-group" in failure for failure in artifacts.summary.review_gate_failures)
    with pytest.raises(ReviewBundleError, match="include-other-group"):
        write_surge_review_bundle(artifacts, tmp_path / "surge.zip", require_review_ready=True)


def test_write_surge_review_bundle_rejects_overlay_self_reference_mismatch(tmp_path) -> None:
    main_conf = _sample_surge_config("https://review.example.com/sub/device/t1/surge.conf?profile=lazycat")
    overlay_conf = _sample_surge_overlay_config(
        "https://review.example.com/sub/device/t1/surge.conf",
        "https://review.example.com/sub/device/t1/surge.conf",
    )
    artifacts = build_surge_review_bundle(
        main_conf,
        source_url="https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is False
    with pytest.raises(ReviewBundleError, match="overlay managed config self-reference"):
        write_surge_review_bundle(artifacts, tmp_path / "surge.zip", require_review_ready=True)


def test_write_surge_review_bundle_rejects_overlay_placeholder_text(tmp_path) -> None:
    main_conf = _sample_surge_config("https://review.example.com/sub/device/t1/surge.conf?profile=lazycat")
    overlay_conf = "\n".join(
        [
            "#!MANAGED-CONFIG https://review.example.com/sub/device/t1/surge-mac-overlay.conf interval=1800 strict=false",
            "#!include https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
            "#!MACOS-ONLY",
            "",
            "# setup: Open SubHub Manage > Advanced > Surge Process Rules / External Proxy Programs.",
            "",
        ]
    )
    artifacts = build_surge_review_bundle(
        main_conf,
        source_url="https://review.example.com/sub/device/t1/surge.conf?profile=lazycat",
        overlay_conf=overlay_conf,
        overlay_source_url="https://review.example.com/sub/device/t1/surge-mac-overlay.conf",
        profile="lazycat",
        git_commit="abc123",
    )

    assert artifacts.summary.review_gate_passed is False
    with pytest.raises(ReviewBundleError, match="placeholder or blocked-publish text"):
        write_surge_review_bundle(artifacts, tmp_path / "surge.zip", require_review_ready=True)
