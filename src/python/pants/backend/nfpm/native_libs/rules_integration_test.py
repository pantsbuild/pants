# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import platform
import sys
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.goals.package_pex_binary import (
    PexBinaryFieldSet,
    PexFromTargetsRequestForBuiltPackage,
)
from pants.backend.python.target_types import PexBinary, PythonRequirementTarget
from pants.backend.python.util_rules import pex_cli, pex_from_targets
from pants.backend.python.util_rules.pex import Pex
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

from .rules import RpmDependsFromPexRequest, RpmDependsInfo
from .rules import rules as native_libs_rules

_PY_TAG = "".join(map(str, sys.version_info[:2]))
_PY_OS = platform.system()  # Linux
_PY_ARCH_TAG = platform.machine()  # x86_64

skip_unless_linux_arm = pytest.mark.skipif(
    _PY_OS != "Linux" or _PY_ARCH_TAG != "aarch64",
    reason="Test case only runs on Linux ARM64",
)
skip_unless_linux_x86_64 = pytest.mark.skipif(
    _PY_OS != "Linux" or _PY_ARCH_TAG != "x86_64",
    reason="Test case only runs on Linux x86_64",
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            PexBinary,
            PythonRequirementTarget,
        ],
        rules=[
            *package_pex_binary.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *pex_cli.rules(),
            *native_libs_rules(),
            QueryRule(PexFromTargetsRequestForBuiltPackage, (PexBinaryFieldSet,)),
            QueryRule(Pex, (PexFromTargetsRequest,)),
            QueryRule(RpmDependsInfo, (RpmDependsFromPexRequest,)),
        ],
    )

    # The rule builds a pex with wheels for the pants venv.
    _py_version = ".".join(map(str, sys.version_info[:3]))

    rule_runner.set_options(
        [
            f"--python-interpreter-constraints=['CPython=={_py_version}']",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def _get_pex_binary(rule_runner: RuleRunner, address: Address) -> Pex:
    pex_binary_tgt = rule_runner.get_target(address)
    pex_binary_field_set = PexBinaryFieldSet.create(pex_binary_tgt)
    build_pex_request = rule_runner.request(
        PexFromTargetsRequestForBuiltPackage, [pex_binary_field_set]
    )
    pex_binary = rule_runner.request(Pex, [build_pex_request.request])
    return pex_binary


@pytest.mark.parametrize(
    "pex_reqs,pex_script,expected_provides,expected_requires",
    (
        pytest.param(["cowsay==4.0"], "cowsay", (), (), id="cowsay"),
        pytest.param(
            ["setproctitle==1.3.6"],
            None,
            (f"_setproctitle.cpython-{_PY_TAG}-x86_64-linux-gnu.so()(64bit)",),
            (
                "libc.so.6()(64bit)",
                "libc.so.6(GLIBC_2.2.5)(64bit)",
                "libpthread.so.0()(64bit)",
                "rtld(GNU_HASH)",
            ),
            marks=(skip_unless_linux_x86_64, pytest.mark.no_error_if_skipped),
            id="setproctitle-x86_64",
        ),
        pytest.param(
            ["setproctitle==1.3.6"],
            None,
            (f"_setproctitle.cpython-{_PY_TAG}-aarch64-linux-gnu.so()(64bit)",),
            (
                "libc.so.6()(64bit)",
                "libc.so.6(GLIBC_2.17)(64bit)",
                "libpthread.so.0()(64bit)",
                "rtld(GNU_HASH)",
            ),
            marks=(skip_unless_linux_arm, pytest.mark.no_error_if_skipped),
            id="setproctitle-arm64",
        ),
    ),
)
def test_rpm_depends_from_pex_rule(
    pex_reqs: list[str],
    pex_script: str | None,
    expected_provides: tuple[str, ...],
    expected_requires: tuple[str, ...],
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""
                python_requirement(name="req", requirements={pex_reqs!r})
                pex_binary(name="pex", script={pex_script!r}, dependencies=[":req"])
                """
            )
        }
    )
    target_pex = _get_pex_binary(rule_runner, Address("", target_name="pex"))
    result = rule_runner.request(RpmDependsInfo, [RpmDependsFromPexRequest(target_pex)])
    assert result.provides == expected_provides
    assert result.requires == expected_requires
