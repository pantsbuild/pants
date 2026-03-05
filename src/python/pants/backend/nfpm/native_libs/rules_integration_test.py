# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import platform
import sys
from textwrap import dedent

import pytest

from pants.backend.nfpm.dependency_inference import rules as nfpm_dependency_inference_rules
from pants.backend.nfpm.fields.rpm import NfpmRpmDependsField, NfpmRpmProvidesField
from pants.backend.nfpm.native_libs.rules import (
    NativeLibsNfpmPackageFieldsRequest,
    RpmDependsFromPexRequest,
    RpmDependsInfo,
)
from pants.backend.nfpm.native_libs.rules import rules as native_libs_rules
from pants.backend.nfpm.rules import rules as nfpm_rules
from pants.backend.nfpm.subsystem import rules as nfpm_subsystem_rules
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_types_rules
from pants.backend.nfpm.util_rules.inject_config import InjectedNfpmPackageFields
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
from pants.util.frozendict import FrozenDict

_PY_TAG = "".join(map(str, sys.version_info[:2]))
_PY_OS = platform.system()  # Linux
_PY_ARCH_TAG = platform.machine()  # x86_64

_PKG_NAME = "pkg"


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
            *nfpm_target_types(),
        ],
        rules=[
            *package_pex_binary.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *pex_cli.rules(),
            *nfpm_subsystem_rules(),
            *nfpm_target_types_rules(),
            *nfpm_dependency_inference_rules(),
            *nfpm_rules(),
            *native_libs_rules(),
            QueryRule(PexFromTargetsRequestForBuiltPackage, (PexBinaryFieldSet,)),
            QueryRule(Pex, (PexFromTargetsRequest,)),
            QueryRule(RpmDependsInfo, (RpmDependsFromPexRequest,)),
            QueryRule(InjectedNfpmPackageFields, (NativeLibsNfpmPackageFieldsRequest,)),
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
            ["setproctitle==1.3.7"],
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
            ["setproctitle==1.3.7"],
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


@pytest.mark.parametrize(
    "packager,pex_reqs,pex_script,nfpm_arch,expected_provides,expected_depends",
    (
        pytest.param(
            "rpm",
            ["setproctitle==1.3.7"],
            None,
            "amd64",
            (f"_setproctitle.cpython-{_PY_TAG}-x86_64-linux-gnu.so()(64bit)",),
            (
                "libc.so.6()(64bit)",
                "libc.so.6(GLIBC_2.2.5)(64bit)",
                "libpthread.so.0()(64bit)",
                "rtld(GNU_HASH)",
            ),
            marks=skip_unless_linux_x86_64,
            id="rpm-setproctitle-amd64",
        ),
        pytest.param(
            "rpm",
            ["setproctitle==1.3.7"],
            None,
            "arm64",
            (f"_setproctitle.cpython-{_PY_TAG}-aarch64-linux-gnu.so()(64bit)",),
            (
                "libc.so.6()(64bit)",
                "libc.so.6(GLIBC_2.17)(64bit)",
                "libpthread.so.0()(64bit)",
                "rtld(GNU_HASH)",
            ),
            marks=skip_unless_linux_arm,
            id="rpm-setproctitle-arm64",
        ),
    ),
)
def test_inject_native_libs_dependencies_in_package_fields_rule(
    packager: str,
    pex_reqs: list[str],
    pex_script: str | None,
    nfpm_arch: str,
    expected_provides: tuple[str, ...],
    expected_depends: tuple[str, ...],
    rule_runner: RuleRunner,
) -> None:
    build_contents = dedent(
        f"""
        python_requirement(name="req", requirements={pex_reqs!r})
        pex_binary(
            name="pex", script={pex_script!r}, dependencies=[":req"], output_path="{_PKG_NAME}.pex"
        )
        nfpm_content_files(
            name="contents",
            files=[("{_PKG_NAME}.pex", "/opt/{_PKG_NAME}/{_PKG_NAME}.pex")],
            dependencies=[":pex"],
            file_owner="root",
            file_group="root",
            file_mode="755",  # same as 0o755 and "rwxr-xr-x"
        )
        nfpm_{packager}_package(
            name="{_PKG_NAME}",
            description="A {packager} package",
            package_name="{_PKG_NAME}",
            version="1.2.3",
            dependencies=[":contents"],
            arch="{nfpm_arch}",
        )
        """
    )

    rule_runner.write_files(
        {
            "BUILD": build_contents,
        }
    )

    target = rule_runner.get_target(Address("", target_name=_PKG_NAME))
    result = rule_runner.request(
        InjectedNfpmPackageFields, [NativeLibsNfpmPackageFieldsRequest(target, FrozenDict())]
    )
    field_values = result.field_values
    if packager == "rpm":
        assert len(field_values) == 2
        assert field_values[NfpmRpmProvidesField].value == expected_provides
        assert field_values[NfpmRpmDependsField].value == expected_depends
