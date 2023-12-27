# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from typing import Any

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_requires_wheels() -> None:
    sources = {
        "src/BUILD": "pex_binary()",
        "src/main.py": "print('hello world')",
    }

    with setup_tmpdir(sources) as tmpdir:
        package_args = [
            "--backend-packages=['pants.backend.python', 'pants.backend.experimental.python.packaging.pyoxidizer']",
            f"--source-root-patterns=['{tmpdir}']",
            "peek",
            "--include-goals",
            f"{tmpdir}/src::",
        ]
        peek_result = run_pants(package_args)
        peek_result.assert_success()

        output: list[dict[str, Any | None]] = json.loads(peek_result.stdout)
        assert len(output) == 1
        assert output[0]["goals"] == ["package", "run"]
