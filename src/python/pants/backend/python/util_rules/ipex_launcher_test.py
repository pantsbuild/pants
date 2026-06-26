# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import subprocess
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pants.backend.python.util_rules import ipex_launcher
from pants.backend.python.util_rules.ipex_launcher import (
    APP_CODE_PREFIX,
    _hydrate_pex_file,
    _requirements_from_pex_info,
)


def _write_ipex(
    path: Path,
    *,
    bootstrap_info: dict[str, Any],
    ipex_info: dict[str, Any] | None = None,
) -> None:
    ipex_info = ipex_info or {
        "code": [f"{APP_CODE_PREFIX}app.py"],
        "resolver_settings": {
            "indexes": ["https://example.invalid/simple"],
            "find_links": ["file:///example/wheels"],
        },
        "pex_args": ["--entry-point", "app:main"],
    }

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("BOOTSTRAP-PEX-INFO", json.dumps(bootstrap_info))
        zf.writestr("IPEX-INFO", json.dumps(ipex_info))
        zf.writestr(f"{APP_CODE_PREFIX}app.py", "def main(): pass\n")


def _capture_hydrate_pex_run(
    monkeypatch: Any, captured: dict[str, Any]
) -> None:
    def fake_run(
        argv: Sequence[str],
        *,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        requirements_path = Path(argv[argv.index("--requirement") + 1])
        sources_dir = Path(argv[argv.index("--sources-directory") + 1])
        captured.update(
            argv=tuple(argv),
            check=check,
            env=env,
            requirements=requirements_path.read_text().splitlines(),
            app_source=(sources_dir / "app.py").read_text(),
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(ipex_launcher.subprocess, "run", fake_run)


def test_requirements_from_pex_info_distributions() -> None:
    assert _requirements_from_pex_info(
        {
            "distributions": {
                "requests-2.32.5-py3-none-any.whl": "",
                "typing_extensions-4.15.0-py3-none-any.whl": "",
            },
            "requirements": ["requests"],
        }
    ) == ("requests==2.32.5", "typing-extensions==4.15.0")


def test_requirements_from_pex_info_falls_back_to_requirements() -> None:
    assert _requirements_from_pex_info({"requirements": ["requests>=2"]}) == ("requests>=2",)


def test_hydrate_pex_file_uses_full_resolved_distribution_set(
    monkeypatch: Any, tmp_path: Path
) -> None:
    ipex_file = tmp_path / "app.ipex"
    hydrated_pex_file = tmp_path / "app.pex"
    _write_ipex(
        ipex_file,
        bootstrap_info={
            "distributions": {
                ".deps/requests-2.32.5-py3-none-any.whl": "",
                ".deps/urllib3-2.5.0-py3-none-any.whl": "",
                ".deps/certifi-2025.11.12-py3-none-any.whl": "",
            },
            "requirements": ["requests==2.32.5"],
        },
    )
    captured: dict[str, Any] = {}
    _capture_hydrate_pex_run(monkeypatch, captured)

    _hydrate_pex_file(str(ipex_file), str(hydrated_pex_file))

    assert captured["check"] is True
    assert captured["requirements"] == [
        "certifi==2025.11.12",
        "requests==2.32.5",
        "urllib3==2.5.0",
    ]
    assert captured["app_source"] == "def main(): pass\n"
    assert "--no-transitive" in captured["argv"]
    assert "--index=https://example.invalid/simple" in captured["argv"]
    assert "--find-links=file:///example/wheels" in captured["argv"]
    assert "--entry-point" in captured["argv"]
    assert "app:main" in captured["argv"]


def test_hydrate_pex_file_falls_back_to_requirements_when_no_distributions(
    monkeypatch: Any, tmp_path: Path
) -> None:
    ipex_file = tmp_path / "app.ipex"
    hydrated_pex_file = tmp_path / "app.pex"
    _write_ipex(
        ipex_file,
        bootstrap_info={
            "requirements": ["requests>=2"],
        },
    )
    captured: dict[str, Any] = {}
    _capture_hydrate_pex_run(monkeypatch, captured)

    _hydrate_pex_file(str(ipex_file), str(hydrated_pex_file))

    assert captured["requirements"] == ["requests>=2"]
    assert "--no-transitive" not in captured["argv"]
