# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent, indent  # noqa: PNT20

import pytest

from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.python_interpreter_selection import (
    python_interpreter_path,
    skip_unless_python310_and_python311_present,
)
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(ProcessResult, [Process]),
        ]
    )


@pytest.mark.platform_specific_behavior
@skip_unless_python310_and_python311_present
def test_interpreter_identity(rule_runner: RuleRunner) -> None:
    __TEST_PLATFORM = "__TEST_PLATFORM"
    __TEST_LIBC_VER = "__TEST_LIBC_VER"

    monkeypatching_identity_script = dedent(
        f"""\
    import os
    from unittest.mock import patch

    with (
        patch("sysconfig.get_platform", return_value=os.environ.get("{__TEST_PLATFORM}", "")),
        patch("platform.libc_ver", return_value=os.environ.get("{__TEST_LIBC_VER}", "")),
    ):
    """
    ) + indent(PythonExecutable.self_identity_script, "    ")

    def get_fingerprint(interpreter_version: str, platform: str, libc_ver: str):
        res = rule_runner.request(
            ProcessResult,
            [
                Process(
                    argv=(
                        python_interpreter_path(interpreter_version),
                        "-c",
                        monkeypatching_identity_script,
                    ),
                    description="",
                    env={__TEST_PLATFORM: platform, __TEST_LIBC_VER: libc_ver},
                )
            ],
        )
        fingerprint = res.stdout.splitlines()[-1].strip()
        assert len(fingerprint) == 64
        return fingerprint

    # Vary each field and make sure all the resulting fingerprints are distinct.
    fingerprints = set()
    for interpreter in ("3.10", "3.11"):
        for platform in ("linux-x86_64", "linux-aarch64"):
            for libc_ver in ("('glibc', '2.39')", "('glibc', '2.41')"):
                fingerprints.add(get_fingerprint(interpreter, platform, libc_ver))

    assert 8 == len(fingerprints)
