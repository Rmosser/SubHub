from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


def test_build_stages_docs_without_reference_projects(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    commands = (root / "lzc-build.yml").read_text().splitlines()
    command = next(line.strip() for line in commands if "scripts/stage_package_docs.py" in line)
    args = shlex.split(command)
    args[:2] = [sys.executable, str(root / args[1])]

    docs = tmp_path / "docs"
    (docs / "deployment").mkdir(parents=True)
    (docs / "index.md").write_text("# Documentation\n")
    (docs / "deployment" / "guide.md").write_text("# Deployment\n")
    references = docs / "参考项目" / "motion" / ".git"
    references.mkdir(parents=True)
    (references / "large-history.pack").write_bytes(b"reference checkout")
    (tmp_path / "dist").mkdir()

    subprocess.run(args, cwd=tmp_path, check=True)

    staged = tmp_path / "dist" / "docs"
    assert (staged / "index.md").read_text() == "# Documentation\n"
    assert (staged / "deployment" / "guide.md").read_text() == "# Deployment\n"
    assert not (staged / "参考项目").exists()
    assert (references / "large-history.pack").exists()
