# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import platform
import sys
from textwrap import dedent

import pytest

from pants.backend.nfpm.native_libs.elfdeps.rules import PexELFInfo, RequestPexELFInfo, SOInfo
from pants.backend.nfpm.native_libs.elfdeps.rules import rules as elfdeps_rules
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
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

# The tests build a pex with wheels for the current platform.
# These vars are used to choose the expected platform-specific test results.
_PY_VERSION = ".".join(map(str, sys.version_info[:3]))
_PY_TAG = "".join(map(str, sys.version_info[:2]))
_PY_OS = platform.system()  # Linux
_PY_ARCH_TAG = platform.machine()  # x86_64
_ELF_BITS_MARKER = "(64bit)" if platform.architecture() == ("64bit", "ELF") else ""


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
            *elfdeps_rules(),
            QueryRule(PexFromTargetsRequestForBuiltPackage, (PexBinaryFieldSet,)),
            QueryRule(Pex, (PexFromTargetsRequest,)),
            QueryRule(PexELFInfo, (RequestPexELFInfo,)),
        ],
    )
    rule_runner.set_options(
        [
            f"--python-interpreter-constraints=['CPython=={_PY_VERSION}']",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


# This has SO versions for the setproctitle==1.3.6 NEEDS libc.so.6 by architecture.
_SETPROCTITLE_LIBC6_SO_VERSIONS = {
    "x86_64": ("", "GLIBC_2.2.5"),
    "aarch64": ("", "GLIBC_2.17"),
    "powerpc64le": ("", "GLIBC_2.17"),
    "i686": ("", "GLIBC_2.0", "GLIBC_2.1.3"),
    "i386": ("", "GLIBC_2.0", "GLIBC_2.1.3"),
}


# @pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "pex_reqs,pex_script,expected_provides,expected_requires",
    (
        pytest.param(["cowsay==4.0"], "cowsay", (), (), id="cowsay"),
        pytest.param(
            ["setproctitle==1.3.6"],
            None,
            (
                SOInfo(
                    soname=f"_setproctitle.cpython-{_PY_TAG}-{_PY_ARCH_TAG}-linux-gnu.so",
                    version="",
                    marker=_ELF_BITS_MARKER,
                    so_info=f"_setproctitle.cpython-{_PY_TAG}-{_PY_ARCH_TAG}-linux-gnu.so(){_ELF_BITS_MARKER}",
                ),
            )
            if _PY_OS == "Linux"
            else (),
            (
                *(
                    SOInfo(
                        soname="libc.so.6",
                        version=so_version,
                        marker=_ELF_BITS_MARKER,
                        so_info=f"libc.so.6({so_version}){_ELF_BITS_MARKER}",
                    )
                    for so_version in _SETPROCTITLE_LIBC6_SO_VERSIONS[_PY_ARCH_TAG]
                ),
                SOInfo(
                    soname="libpthread.so.0",
                    version="",
                    marker=_ELF_BITS_MARKER,
                    so_info=f"libpthread.so.0(){_ELF_BITS_MARKER}",
                ),
                SOInfo(soname="rtld", version="GNU_HASH", marker="", so_info="rtld(GNU_HASH)"),
            )
            if _PY_OS == "Linux"
            else (),
            id="setproctitle",
        ),
    ),
)
def test_elfdeps_analyze_pex_wheels(
    pex_reqs: list[str],
    pex_script: str | None,
    expected_provides: tuple[SOInfo, ...],
    expected_requires: tuple[SOInfo, ...],
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

    pex_binary_tgt = rule_runner.get_target(Address("", target_name="pex"))
    pex_binary_field_set = PexBinaryFieldSet.create(pex_binary_tgt)
    build_pex_request = rule_runner.request(
        PexFromTargetsRequestForBuiltPackage, [pex_binary_field_set]
    )
    pex_binary = rule_runner.request(Pex, [build_pex_request.request])

    result = rule_runner.request(PexELFInfo, [RequestPexELFInfo(pex_binary)])
    assert result.provides == expected_provides
    assert result.requires == expected_requires
