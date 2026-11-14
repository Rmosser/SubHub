#!/usr/bin/env python3
"""SubHub's versioned pip wheelhouse protocol and unprivileged CI consumer.

Vendor this file unchanged as SubHub/scripts/ci_pip_cache.py. The producer uses
its own reviewed copy, never Python code fetched from the consumer repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPOSITORY = "SubHub"
IMAGE = "127.0.0.1:17892/woodpecker/python313@sha256:87104faaf9ab1fc017386cf41da7c34b7f93d6328932a31d8a7101bca44342aa"
IMAGE_ID = "sha256:8716c811e3b124ddc8e314573cdee5dd7b713aefa0a1509c644e1ce0c88cdeb3"
PYTHON = "3.13.14"
PIP = "26.1.2"
LOCK = "ci/requirements-linux-py313.lock"
INPUTS = ("requirements.txt", "requirements-dev.txt")
SOURCES = (*INPUTS, LOCK)
FORMAT = "pip-wheelhouse-v1"
BASE_URL = "http://172.18.0.1:17894/v1/uv"
PROXY = "http://172.18.0.1:17896"
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAjiaprN7h6eHsAeYuK38mKr6HOHfD9dzC6Dp2WXcqNpU=
-----END PUBLIC KEY-----
"""
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
ENTRY = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*) --hash=sha256:([0-9a-f]{64})")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def source_header(root: Path) -> str:
    return "".join(f"# source {name} sha256:{digest((root / name).read_bytes())}\n" for name in INPUTS)


def validate_lock(root: Path) -> dict[str, tuple[str, str]]:
    text = (root / LOCK).read_text()
    if not text.startswith(f"# {FORMAT}; Python {PYTHON}; pip {PIP}; linux-x86_64\n" + source_header(root)):
        raise ValueError("CI lock is stale; regenerate it from both requirements files")
    result = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = ENTRY.fullmatch(line)
        if not match:
            raise ValueError("CI lock must contain only exact public package pins and SHA-256 hashes")
        name, version, sha = match.groups()
        name = canonical_name(name)
        if name in result:
            raise ValueError("duplicate package in CI lock")
        result[name] = (version, sha)
    if not result:
        raise ValueError("empty CI lock")
    return result


def identity(root: Path) -> dict:
    validate_lock(root)
    return {
        "schema": 1, "repository": REPOSITORY, "cache_format": FORMAT,
        "platform": "linux-x86_64", "python_version": PYTHON,
        "pip_version": PIP, "image": IMAGE,
        "sources": {name: digest((root / name).read_bytes()) for name in SOURCES},
    }


def cache_key(value: dict) -> str:
    return "subhub-pip-" + digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())[:48]


def write_lock(root: Path, report: Path) -> None:
    value = json.loads(report.read_text())
    environment = value.get("environment", {})
    if (value.get("pip_version") != PIP or environment.get("platform_system") != "Linux"
            or environment.get("platform_machine") != "x86_64" or environment.get("python_full_version") != PYTHON):
        raise ValueError("resolve the CI lock inside the pinned linux/amd64 Python image")
    rows = {}
    for item in value["install"]:
        download = item["download_info"]
        url = urlparse(download["url"])
        sha = download["archive_info"]["hashes"]["sha256"]
        if url.scheme != "https" or url.hostname != "files.pythonhosted.org" or not url.path.endswith(".whl"):
            raise ValueError("only public PyPI wheels are eligible")
        name = canonical_name(item["metadata"]["name"])
        if name in rows:
            raise ValueError("duplicate resolved package")
        rows[name] = f"{name}=={item['metadata']['version']} --hash=sha256:{sha}\n"
    path = root / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {FORMAT}; Python {PYTHON}; pip {PIP}; linux-x86_64\n" + source_header(root) + "".join(rows[n] for n in sorted(rows)))
    validate_lock(root)


@contextmanager
def deadline(seconds: float):
    previous = signal.getsignal(signal.SIGALRM)
    def expired(_signum, _frame):
        raise TimeoutError("cache total deadline exceeded")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("cache redirects are forbidden")


def fetch(url: str, path: Path, limit: int) -> int:
    opener = build_opener(ProxyHandler({}), NoRedirect())
    count = 0
    with opener.open(Request(url), timeout=3) as response, path.open("xb") as out:
        length = response.headers.get("Content-Length")
        if length is not None and not 0 <= int(length) <= limit:
            raise ValueError("cache response exceeds byte limit")
        while chunk := response.read(min(65536, limit - count + 1)):
            count += len(chunk)
            if count > limit:
                raise ValueError("cache response exceeds byte limit")
            out.write(chunk)
        if length is not None and count != int(length):
            raise ValueError("truncated cache response")
    return count


def extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tf:
        total, names, members = 0, set(), []
        for entry in tf:
            total += entry.size
            if (not entry.isfile() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+!-]*\.whl", entry.name)
                    or entry.name in names or entry.size < 0 or total > MAX_EXPANDED or len(names) >= 512):
                raise ValueError("unsafe or oversized wheelhouse archive")
            names.add(entry.name)
            members.append(entry)
        if not names:
            raise ValueError("empty wheelhouse archive")
        destination.mkdir(mode=0o700)
        for entry in members:
            with tf.extractfile(entry) as source, (destination / entry.name).open("xb") as out:
                shutil.copyfileobj(source, out)


def restore(root: Path, stage: Path) -> tuple[Path, int]:
    expected = identity(root)
    key = cache_key(expected)
    url = f"{BASE_URL}/{key}"
    with deadline(30):
        fetch(url + "/manifest.json", stage / "manifest.json", 16384)
        fetch(url + "/manifest.sig", stage / "manifest.sig", 128)
        (stage / "public.pem").write_text(PUBLIC_KEY)
        subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-rawin", "-inkey", str(stage / "public.pem"),
                        "-in", str(stage / "manifest.json"), "-sigfile", str(stage / "manifest.sig")],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        manifest = json.loads((stage / "manifest.json").read_bytes())
        if (manifest.get("identity") != expected or manifest.get("cache_key") != key
                or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_sha", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("archive_sha256", "")))
                or type(manifest.get("archive_bytes")) is not int
                or not 0 < manifest["archive_bytes"] <= MAX_ARCHIVE):
            raise ValueError("snapshot identity mismatch")
        count = fetch(url + "/archive.tar.gz", stage / "archive.tar.gz", manifest["archive_bytes"])
        if count != manifest["archive_bytes"] or digest((stage / "archive.tar.gz").read_bytes()) != manifest["archive_sha256"]:
            raise ValueError("snapshot checksum mismatch")
        extract(stage / "archive.tar.gz", stage / "wheels")
    return stage / "wheels", count


def pip_environment(proxy: str | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIP_") and k.lower() not in
           {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    if proxy:
        env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, NO_PROXY="127.0.0.1,localhost,172.18.0.1")
    return env


def create_venv(root: Path) -> None:
    if (root / ".venv").is_symlink():
        raise ValueError(".venv must not be a symlink")
    subprocess.run([sys.executable, "-m", "venv", "--clear", ".venv"], cwd=root, env=pip_environment(), check=True, timeout=30)


def install_packages(root: Path, wheels: Path | None, proxy: str | None, timeout: int) -> None:
    command = [str(root / ".venv/bin/python"), "-m", "pip", "install", "--require-hashes", "--only-binary=:all:",
               "--timeout", "10", "--retries", "1", "-r", LOCK]
    command += ["--no-index", "--find-links", str(wheels)] if wheels else ["--index-url", "https://pypi.org/simple"]
    subprocess.run(command, cwd=root, env=pip_environment(proxy), check=True, timeout=timeout)
    subprocess.run([str(root / ".venv/bin/python"), "-m", "pip", "check"], cwd=root, env=pip_environment(), check=True, timeout=15)


def install(root: Path) -> None:
    expected = identity(root)
    if platform.system() != "Linux" or platform.machine() != "x86_64" or platform.python_version() != PYTHON:
        raise ValueError("CI wheel lock requires the pinned linux/amd64 Python image")
    import ensurepip
    if ensurepip.version() != PIP:
        raise ValueError("bundled pip version differs from the cache identity")
    mode = os.environ.get("CI_CACHE_MODE", "auto")
    if mode not in {"auto", "off"}:
        raise ValueError("CI_CACHE_MODE must be auto or off")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="subhub-pip-") as temp:
        hot, count = False, None
        if mode == "auto":
            try:
                wheels, count = restore(root, Path(temp))
                create_venv(root)
                install_packages(root, wheels, None, 60)
                hot = True
            except (OSError, ValueError, TimeoutError, subprocess.SubprocessError, tarfile.TarError):
                print("CI pip snapshot unavailable or invalid; retrying with locked public PyPI wheels", flush=True)
        if not hot:
            create_venv(root)
            try:
                install_packages(root, None, PROXY, 120)
                network = "eb-fast-proxy"
            except (OSError, subprocess.SubprocessError):
                print("CI pip proxy install failed; retrying direct PyPI in a fresh venv", flush=True)
                create_venv(root)
                install_packages(root, None, None, 180)
                network = "direct"
        else:
            network = "offline"
        print("CI_CACHE_PHASE " + json.dumps({
            "phase": "package_install", "mode": "hot" if hot else "fallback", "status": "ok",
            "cache_key": cache_key(expected), "duration_ms": round((time.monotonic() - started) * 1000),
            "downloaded_bytes": count if hot else None, "cache_hit": hot, "network": network,
        }), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check-lock", action="store_true")
    group.add_argument("--key", action="store_true")
    group.add_argument("--write-lock", type=Path, metavar="PIP_REPORT")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.write_lock:
        write_lock(root, args.write_lock)
    elif args.check_lock:
        validate_lock(root)
    elif args.key:
        print(cache_key(identity(root)))
    else:
        install(root)


if __name__ == "__main__":
    main()
