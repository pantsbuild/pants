# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any, ContextManager, cast

import pytest
from _pytest.mark import ParameterSet

from pants.backend.nfpm.dependency_inference import rules as nfpm_dependency_inference_rules
from pants.backend.nfpm.field_sets import (
    NFPM_PACKAGE_FIELD_SET_TYPES,
    NfpmApkPackageFieldSet,
    NfpmDebPackageFieldSet,
    NfpmPackageFieldSet,
    NfpmRpmPackageFieldSet,
)
from pants.backend.nfpm.rules import rules as nfpm_rules
from pants.backend.nfpm.subsystem import rules as nfpm_subsystem_rules
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_types_rules
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget, FileTarget
from pants.core.target_types import rules as core_target_type_rules
from pants.engine.internals.native_engine import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import Target
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            FileTarget,
            FilesGeneratorTarget,
            *nfpm_target_types(),
        ],
        rules=[
            *core_target_type_rules(),
            *nfpm_subsystem_rules(),
            *nfpm_target_types_rules(),
            *nfpm_dependency_inference_rules(),
            *nfpm_rules(),
            *(
                QueryRule(BuiltPackage, [field_set_type])
                for field_set_type in NFPM_PACKAGE_FIELD_SET_TYPES
            ),
        ],
    )
    return rule_runner


def build_package(
    rule_runner: RuleRunner,
    binary_target: Target,
    field_set_type: type[NfpmPackageFieldSet],
) -> BuiltPackage:
    field_set = field_set_type.create(binary_target)
    result = rule_runner.request(BuiltPackage, [field_set])
    rule_runner.write_digest(result.digest)
    return result


def _assert_one_built_artifact(
    pkg_name: str, built_package: BuiltPackage, field_set_type: type[NfpmPackageFieldSet]
) -> None:
    assert len(built_package.artifacts) == 1
    artifact = built_package.artifacts[0]
    relpath = artifact.relpath or ""
    assert relpath.endswith(field_set_type.extension)
    assert relpath.startswith(f"{pkg_name}/{pkg_name}")


_PKG_NAME = "pkg"
_PKG_VERSION = "3.2.1"

_TEST_CASES: tuple[ParameterSet, ...] = (
    # apk
    pytest.param(NfpmApkPackageFieldSet, {}, True, id="apk-minimal-metadata"),
    pytest.param(
        NfpmApkPackageFieldSet,
        # apk uses "maintainer" not "packager"
        {"packager": "Arch Maintainer <arch-maintainer@example.com>"},
        False,
        id="apk-invalid-field-packager",
    ),
    pytest.param(
        NfpmApkPackageFieldSet,
        {
            "homepage": "https://apk.example.com",
            "license": "Apache-2.0",
            "maintainer": "APK Maintainer <apk-maintainer@example.com>",
            "replaces": ["some-command"],
            "provides": [f"cmd:some-command={_PKG_VERSION}"],
            "depends": ["bash", "git=2.40.1-r0", "/bin/sh", "so:libcurl.so.4"],
            "scripts": {"postinstall": "postinstall.sh", "postupgrade": "apk-postupgrade.sh"},
        },
        True,
        id="apk-extra-metadata",
    ),
    # deb
    pytest.param(NfpmDebPackageFieldSet, {}, False, id="deb-missing-maintainer-field"),
    pytest.param(
        NfpmDebPackageFieldSet,
        # deb uses "maintainer" not "packager"
        {"packager": "Deb Maintainer <deb-maintainer@example.com>"},
        False,
        id="deb-invalid-field-packager",
    ),
    pytest.param(
        NfpmDebPackageFieldSet,
        # maintainer is a required field
        {"maintainer": "Deb Maintainer <deb-maintainer@example.com>"},
        True,
        id="deb-minimal-metadata",
    ),
    pytest.param(
        NfpmDebPackageFieldSet,
        {
            "homepage": "https://deb.example.com",
            "license": "Apache-2.0",
            "maintainer": "deb-maintainer@example.com",
            "section": "education",
            "priority": "standard",  # defaults to optional
            "fields": {"XB-Custom": "custom control file field"},
            "triggers": {"interest_noawait": ["some-trigger"]},
            "replaces": ["partial-pkg", "replaced-pkg"],
            "provides": ["pkg"],
            "depends": ["git", "libc6 (>= 2.2.1)", "default-mta | mail-transport-agent"],
            "recommends": ["other-pkg"],
            "suggests": ["beneficial-other-pkg"],
            "conflicts": ["replaced-pkg"],
            "breaks": ["partial-pkg"],
            "compression": "none",  # defaults to gzip
            "scripts": {"postinstall": "postinstall.sh", "config": "deb-config.sh"},
        },
        True,
        id="deb-extra-metadata",
    ),
    # rpm
    pytest.param(NfpmRpmPackageFieldSet, {}, True, id="rpm-minimal-metadata"),
    pytest.param(
        NfpmRpmPackageFieldSet,
        # rpm uses "packager" not "maintainer"
        {"maintainer": "RPM Maintainer <rpm-maintainer@example.com>"},
        False,
        id="rpm-invalid-field-maintainer",
    ),
    pytest.param(
        NfpmRpmPackageFieldSet,
        {
            "homepage": "https://rpm.example.com",
            "license": "Apache-2.0",
            "packager": "RPM Maintainer <rpm-maintainer@example.com>",
            "vendor": "Example Organization",
            "prefixes": ["/usr", "/usr/local", "/opt/foobar"],
            "replaces": ["partial-pkg", "replaced-pkg"],
            "provides": ["pkg"],
            "depends": ["git", "libc6 (>= 2.2.1)", "default-mta | mail-transport-agent"],
            "recommends": ["other-pkg"],
            "suggests": ["beneficial-other-pkg"],
            "conflicts": ["replaced-pkg"],
            "compression": "zstd:fastest",  # defaults to gzip:-1
            "scripts": {"postinstall": "postinstall.sh", "verify": "rpm-verify.sh"},
            "ghost_contents": ["/var/log/pkg.log"],
        },
        True,
        id="rpm-extra-metadata",
    ),
)


@pytest.mark.parametrize("field_set_type,extra_metadata,valid_target", _TEST_CASES)
def test_generate_package_without_contents(
    rule_runner: RuleRunner,
    field_set_type: type[NfpmPackageFieldSet],
    extra_metadata: dict[str, Any],
    valid_target: bool,
) -> None:
    packager = field_set_type.packager
    # do not use scripts for this test.
    extra_metadata = {key: value for key, value in extra_metadata.items() if key != "scripts"}
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""
                nfpm_{packager}_package(
                    name="{_PKG_NAME}",
                    package_name="{_PKG_NAME}",
                    version="{_PKG_VERSION}",
                    **{extra_metadata}
                )
                """
            ),
        }
    )

    # noinspection DuplicatedCode
    with cast(ContextManager, no_exception()) if valid_target else pytest.raises(ExecutionError):
        binary_tgt = rule_runner.get_target(Address("", target_name="pkg"))
    if not valid_target:
        return

    built_package = build_package(rule_runner, binary_tgt, field_set_type)
    _assert_one_built_artifact(_PKG_NAME, built_package, field_set_type)


@pytest.mark.parametrize("field_set_type,extra_metadata,valid_target", _TEST_CASES)
def test_generate_package_with_contents(
    rule_runner: RuleRunner,
    field_set_type: type[NfpmPackageFieldSet],
    extra_metadata: dict[str, Any],
    valid_target: bool,
) -> None:
    packager = field_set_type.packager
    scripts = extra_metadata.get("scripts", {})
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""
                nfpm_{packager}_package(
                    name="{_PKG_NAME}",
                    package_name="{_PKG_NAME}",
                    version="{_PKG_VERSION}",
                    dependencies=[
                        "contents:files",
                        "contents:file",
                        "contents:symlinks",
                        "contents:symlink",
                        "contents:dirs",
                        "contents:dir",
                    ],
                    **{extra_metadata}
                )
                if {bool(scripts)}:
                    files(
                        name="scripts",
                        sources={list(scripts.values())},
                    )
                """
            ),
            **{path: "" for path in scripts.values()},
            "contents/BUILD": dedent(
                f"""
                file(
                    name="sandbox_file",
                    source="sandbox-file.txt",
                )
                nfpm_content_files(
                    name="files",
                    files=[
                        ("sandbox-file.txt", "/usr/share/{_PKG_NAME}/{_PKG_NAME}.{_PKG_VERSION}/installed-file.txt"),
                        ("sandbox-file.txt", "/etc/{_PKG_NAME}/installed-file.txt"),
                    ],
                    dependencies=[":sandbox_file"],
                    overrides={{
                        "/etc/{_PKG_NAME}/installed-file.txt": dict(
                            content_type="config",
                            file_mode="rw-------",  # same as 0o600 and "600"
                            file_group="root",
                        ),
                    }},
                    content_type="doc",
                    file_owner="root",
                    file_group="{_PKG_NAME}",
                    file_mode="644",  # same as 0o644 and "rw-r--r--"
                )
                nfpm_content_file(
                    name="file",
                    source="some-executable",
                    dst="/usr/bin/some-executable",
                    file_mode=0o755,  # same as "755" and "rwxr-xr-x"
                )
                nfpm_content_symlinks(
                    name="symlinks",
                    symlinks=(
                        ("some-executable", "/usr/bin/new-relative-symlinked-exe"),
                        ("/usr/bin/some-executable", "/usr/bin/new-absolute-symlinked-exe"),
                    ),
                    overrides={{
                        "/usr/bin/new-relative-symlinked-exe": dict(file_group="special-group"),
                    }},
                )
                nfpm_content_symlink(
                    name="symlink",
                    src="/usr/bin/some-executable",
                    dst="/usr/sbin/sbin-executable",
                )
                nfpm_content_dirs(
                    name="dirs",
                    dirs=["/usr/share/{_PKG_NAME}"],
                    overrides={{
                        "/usr/share/{_PKG_NAME}": dict(file_group="special-group"),
                    }},
                )
                nfpm_content_dir(
                    name="dir",
                    dst="/etc/{_PKG_NAME}",
                    file_mode=0o700,
                )
                """
            ),
            "contents/sandbox-file.txt": "",
            "contents/some-executable": "",
        }
    )

    # noinspection DuplicatedCode
    with cast(ContextManager, no_exception()) if valid_target else pytest.raises(ExecutionError):
        binary_tgt = rule_runner.get_target(Address("", target_name=_PKG_NAME))
    if not valid_target:
        return

    built_package = build_package(rule_runner, binary_tgt, field_set_type)
    _assert_one_built_artifact(_PKG_NAME, built_package, field_set_type)
