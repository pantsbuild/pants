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

from .rules import (
    DebDependsFromPexRequest,
    DebDependsInfo,
    RpmDependsFromPexRequest,
    RpmDependsInfo,
)
from .rules import rules as native_libs_rules

_PY_TAG = "".join(map(str, sys.version_info[:2]))
_PY_OS = platform.system()  # Linux
_PY_ARCH_TAG = platform.machine()  # x86_64


def _skip_unless(
    os: str, arch: str, extra_reason: str | None = None
) -> tuple[pytest.MarkDecorator, ...]:
    return (
        pytest.mark.no_error_if_skipped,
        pytest.mark.skipif(
            _PY_OS != os or _PY_ARCH_TAG != arch,
            reason=f"Test case only runs on {os} {arch}{' ' + extra_reason if extra_reason else ''}",
        ),
    )


skip_unless_linux_arm = _skip_unless(os="Linux", arch="aarch64")
skip_unless_linux_x86_64 = _skip_unless(os="Linux", arch="x86_64")


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
            QueryRule(DebDependsInfo, (DebDependsFromPexRequest,)),
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
    "pex_reqs,pex_script,distro,distro_codename,debian_arch,expected_packages",
    (
        pytest.param(
            ["cowsay==4.0"],
            "cowsay",
            "ubuntu",
            "jammy",
            "arm64",
            (),
            id="cowsay-ubuntu-jammy-arm64",
        ),
        pytest.param(
            ["setproctitle==1.3.6"],
            None,
            "ubuntu",
            "jammy",
            "arm64",
            (),
            id="setproctitle-ubuntu-jammy-arm64",
        ),
    ),
)
def test_deb_depends_from_pex_rule(
    pex_reqs: list[str],
    pex_script: str | None,
    distro: str,
    distro_codename: str,
    debian_arch: str,
    expected_packages: tuple[str, ...],
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
    result = rule_runner.request(
        DebDependsInfo, [DebDependsFromPexRequest(target_pex, distro, distro_codename, debian_arch)]
    )
    assert result.requires == expected_packages


@pytest.mark.parametrize(
    "whl_dist,whl_resource,whl_py_tag,distro,distro_codename,debian_arch,expected_packages",
    (
        pytest.param(
            "python-ldap",
            "python_ldap-3.4.4-cp311-cp311-linux_x86_64.whl",
            "cp311",
            "ubuntu",
            "jammy",
            "amd64",
            ("libldap-2.5-0",),
            marks=_skip_unless(
                os="Linux",
                arch="x86_64",
                extra_reason="(python-ldap wheel not included for other platforms)",
            ),
            id="ldap-ubuntu-jammy-amd64",
        ),
    ),
)
def test_deb_depends_from_pex_rule_with_whl_resource(
    whl_dist: str,
    whl_resource: str,
    whl_py_tag: str,
    distro: str,
    distro_codename: str,
    debian_arch: str,
    expected_packages: tuple[str, ...],
    rule_runner: RuleRunner,
) -> None:
    assert whl_resource.endswith(".whl")
    whl_contents = read_resource(__name__, whl_resource)
    assert whl_contents is not None

    # NOTE: Renaming the wheel in this test is a hack for forwards compatibility.
    # The test only needs a whl with an ELF .so that can be statically analyzed to look up packages.
    # The other details (os, distro, distro_codename, arch) are hard-coded for this test,
    # except for python version (the only variable that is likely to change over time).
    # So, this replaces the python tag, pretending the wheel is for the current python version.
    whl = whl_resource.replace(whl_py_tag, f"cp{_PY_TAG}")

    rule_runner.write_files(
        {
            whl: whl_contents,
            "BUILD": dedent(
                f"""
                file(name="whl", source={whl!r})
                python_requirement(
                    name="req",
                    dependencies=[":whl"],
                    requirements=["{whl_dist} @ file://{rule_runner.build_root}/{whl}"],
                )
                pex_binary(name="pex", dependencies=[":req"])
                """
            ),
        }
    )

    target_pex = _get_pex_binary(rule_runner, Address("", target_name="pex"))
    result = rule_runner.request(
        DebDependsInfo, [DebDependsFromPexRequest(target_pex, distro, distro_codename, debian_arch)]
    )
    assert result.requires == expected_packages


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
            marks=skip_unless_linux_x86_64,
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
            marks=skip_unless_linux_arm,
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
