#!/usr/bin/env python3
"""Local fault-injection checks for the pip snapshot trust/fallback boundary."""
import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = ROOT / "ci-cache/pip_snapshot.py"
if not PROTOCOL.exists():
    PROTOCOL = ROOT / "scripts/ci_pip_cache.py"
spec = importlib.util.spec_from_file_location("pip_snapshot", PROTOCOL)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


@contextmanager
def server(files, drip=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/archive.tar.gz")
                self.end_headers()
                return
            body = files.get(self.path.rsplit("/", 1)[-1])
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if drip:
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(.02)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}"
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "requirements.txt").write_text("example==1.0\n")
        (self.root / "requirements-dev.txt").write_text("-r requirements.txt\n")
        (self.root / p.LOCK).parent.mkdir()
        (self.root / p.LOCK).write_text(f"# {p.FORMAT}; Python {p.PYTHON}; pip {p.PIP}; linux-x86_64\n" + p.source_header(self.root) + "example==1.0 --hash=sha256:" + "a" * 64 + "\n")

    def test_source_and_lock_changes_cannot_reuse_key(self):
        before = p.cache_key(p.identity(self.root))
        lock = self.root / p.LOCK
        lock.write_text(lock.read_text().replace("a" * 64, "b" * 64))
        self.assertNotEqual(before, p.cache_key(p.identity(self.root)))
        (self.root / "requirements.txt").write_text("example==2.0\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            p.identity(self.root)

    def test_lock_rejects_url_options_unpinned_and_duplicates(self):
        lock = self.root / p.LOCK
        good = lock.read_text()
        for bad in ("https://example.com/a.whl", "--extra-index-url https://example.com", "example>=1", good.splitlines()[-1]):
            lock.write_text(good + bad + "\n")
            with self.assertRaises(ValueError):
                p.validate_lock(self.root)

    def test_lock_generator_requires_exact_runtime_and_public_wheels(self):
        report = {"pip_version": p.PIP, "environment": {"platform_system": "Linux", "platform_machine": "x86_64", "python_full_version": p.PYTHON},
                  "install": [{"download_info": {"url": "https://files.pythonhosted.org/example.whl", "archive_info": {"hashes": {"sha256": "a" * 64}}}, "metadata": {"name": "example", "version": "1.0"}}]}
        path = self.root / "report.json"
        path.write_text(json.dumps(report))
        p.write_lock(self.root, path)
        self.assertEqual(p.validate_lock(self.root)["example"], ("1.0", "a" * 64))
        report["environment"]["platform_system"] = "Darwin"
        path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            p.write_lock(self.root, path)
        report["environment"]["platform_system"] = "Linux"
        report["install"][0]["download_info"]["url"] = "https://private.invalid/example.whl"
        path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            p.write_lock(self.root, path)

    def archive(self, entries):
        path = self.root / "archive.tar.gz"
        with tarfile.open(path, "w:gz") as tf:
            for name, kind in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.size = 1 if kind == tarfile.REGTYPE else 0
                item.linkname = "outside"
                tf.addfile(item, io.BytesIO(b"x") if item.size else None)
        return path

    def test_archive_accepts_only_unique_flat_regular_wheels(self):
        archive = self.archive([("example-1.0-py3-none-any.whl", tarfile.REGTYPE)])
        p.extract(archive, self.root / "good")
        self.assertEqual((self.root / "good/example-1.0-py3-none-any.whl").read_bytes(), b"x")
        for entries in (
            [("../escape.whl", tarfile.REGTYPE)], [("/abs.whl", tarfile.REGTYPE)],
            [("dir/a.whl", tarfile.REGTYPE)], [("link.whl", tarfile.SYMTYPE)],
            [("link.whl", tarfile.LNKTYPE)], [("a.whl", tarfile.REGTYPE)] * 2,
        ):
            with self.assertRaises(ValueError):
                p.extract(self.archive(entries), self.root / "bad")

    def test_fetch_size_redirect_and_drip_deadline(self):
        with server({"body": b"x" * 100}, drip=True) as url:
            with self.assertRaises(ValueError):
                p.fetch(url + "/body", self.root / "large", 10)
            with self.assertRaises(ValueError):
                p.fetch(url + "/redirect", self.root / "redirect", 100)
            start = time.monotonic()
            with self.assertRaises(TimeoutError), p.deadline(.12):
                p.fetch(url + "/body", self.root / "drip", 100)
            self.assertLess(time.monotonic() - start, .8)

    def test_real_signature_identity_and_archive_checksum(self):
        private, public = self.root / "private.pem", self.root / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True, stderr=subprocess.DEVNULL)
        subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, stderr=subprocess.DEVNULL)
        archive = self.archive([("example-1.0-py3-none-any.whl", tarfile.REGTYPE)]).read_bytes()
        identity = p.identity(self.root)
        manifest = {"identity": identity, "cache_key": p.cache_key(identity), "source_sha": "c" * 40,
                    "archive_bytes": len(archive), "archive_sha256": p.digest(archive)}
        path = self.root / "manifest.json"
        def signed(value):
            path.write_text(json.dumps(value))
            subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private), "-in", str(path), "-out", str(self.root / "sig")], check=True)
            return {"manifest.json": path.read_bytes(), "manifest.sig": (self.root / "sig").read_bytes(), "archive.tar.gz": archive}
        good = signed(manifest)
        for index, files in enumerate((good, dict(good, **{"manifest.sig": b"bad"}), dict(good, **{"archive.tar.gz": archive[:-1] + b"x"}), signed(dict(manifest, identity=dict(identity, python_version="wrong"))))):
            stage = self.root / f"stage-{index}"
            stage.mkdir()
            with server(files) as url, patch.object(p, "BASE_URL", url), patch.object(p, "PUBLIC_KEY", public.read_text()):
                if index == 0:
                    wheels, count = p.restore(self.root, stage)
                    self.assertEqual(count, len(archive))
                    self.assertTrue(wheels.is_dir())
                else:
                    with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                        p.restore(self.root, stage)

    def runtime(self, stack):
        for field, result in (("system", "Linux"), ("machine", "x86_64"), ("python_version", p.PYTHON)):
            stack.enter_context(patch.object(p.platform, field, return_value=result))
        stack.enter_context(patch("ensurepip.version", return_value=p.PIP))
        stack.enter_context(patch.dict(p.os.environ, {"CI_CACHE_MODE": "auto"}))

    def test_hit_never_calls_network_pip(self):
        with ExitStack() as stack:
            self.runtime(stack)
            stack.enter_context(patch.object(p, "restore", return_value=(self.root / "wheels", 123)))
            create = stack.enter_context(patch.object(p, "create_venv"))
            install = stack.enter_context(patch.object(p, "install_packages"))
            p.install(self.root)
            create.assert_called_once()
            install.assert_called_once_with(self.root, self.root / "wheels", None, 60)

    def test_failed_offline_and_proxy_get_clean_direct_retry(self):
        with ExitStack() as stack:
            self.runtime(stack)
            stack.enter_context(patch.object(p, "restore", return_value=(self.root / "wheels", 123)))
            create = stack.enter_context(patch.object(p, "create_venv"))
            install = stack.enter_context(patch.object(p, "install_packages", side_effect=[subprocess.CalledProcessError(1, "pip"), subprocess.TimeoutExpired("pip", 120), None]))
            p.install(self.root)
            self.assertEqual(create.call_count, 3)
            self.assertEqual(install.call_args_list[-1].args, (self.root, None, None, 180))

    def test_missing_snapshot_uses_locked_proxy_then_propagates_public_failure(self):
        with ExitStack() as stack:
            self.runtime(stack)
            stack.enter_context(patch.object(p, "restore", side_effect=OSError("unavailable")))
            stack.enter_context(patch.object(p, "create_venv"))
            install = stack.enter_context(patch.object(p, "install_packages", side_effect=subprocess.CalledProcessError(1, "pip")))
            with self.assertRaises(subprocess.CalledProcessError):
                p.install(self.root)
            self.assertEqual(install.call_count, 2)
            self.assertEqual(install.call_args_list[0].args, (self.root, None, p.PROXY, 120))


if __name__ == "__main__":
    unittest.main()
