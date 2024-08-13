# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any, ContextManager, cast

import pytest
import yaml

from pants.backend.nfpm.config import NfpmFileInfo
from pants.backend.nfpm.dependency_inference import rules as nfpm_dependency_inference_rules
from pants.backend.nfpm.field_sets import (
    NFPM_CONTENT_FIELD_SET_TYPES,
    NfpmApkPackageFieldSet,
    NfpmArchlinuxPackageFieldSet,
    NfpmContentFieldSet,
    NfpmDebPackageFieldSet,
    NfpmPackageFieldSet,
    NfpmRpmPackageFieldSet,
)
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_types_rules
from pants.backend.nfpm.util_rules.generate_config import (
    NfpmPackageConfig,
    NfpmPackageConfigRequest,
)
from pants.backend.nfpm.util_rules.generate_config import rules as nfpm_generate_config_rules
from pants.core.target_types import FilesGeneratorTarget, FileTarget
from pants.core.target_types import rules as core_target_type_rules
from pants.engine.fs import CreateDigest, DigestContents, FileContent
from pants.engine.internals.native_engine import EMPTY_DIGEST, Address, Digest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.unions import UnionRule
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import RuleRunner

_PKG_NAME = "pkg"
_PKG_VERSION = "3.2.1"


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
            *nfpm_target_types_rules(),
            *nfpm_dependency_inference_rules(),
            *nfpm_generate_config_rules(),
            *(
                UnionRule(NfpmContentFieldSet, field_set_type)
                for field_set_type in NFPM_CONTENT_FIELD_SET_TYPES
            ),
            QueryRule(NfpmPackageConfig, (NfpmPackageConfigRequest,)),
            QueryRule(DigestContents, (Digest,)),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


@pytest.mark.parametrize(
    (
        "packager",
        "field_set_type",
        "dependencies",
        "scripts",
        "content_sandbox_files",
        "extra_metadata",
        "expect_raise",
    ),
    (
        # no dependencies
        ("apk", NfpmApkPackageFieldSet, [], {}, [], {}, None),
        ("archlinux", NfpmArchlinuxPackageFieldSet, [], {}, [], {}, None),
        ("deb", NfpmDebPackageFieldSet, [], {}, [], {}, None),
        ("rpm", NfpmRpmPackageFieldSet, [], {}, [], {}, None),
        ("rpm", NfpmRpmPackageFieldSet, [], {}, [], {"ghost_contents": ["/var/log/pkg.log"]}, None),
        # no dependencies (extra file does not cause errors)
        ("apk", NfpmApkPackageFieldSet, [], {}, ["contents/extra-file.txt"], {}, None),
        ("archlinux", NfpmArchlinuxPackageFieldSet, [], {}, ["contents/extra-file.txt"], {}, None),
        ("deb", NfpmDebPackageFieldSet, [], {}, ["contents/extra-file.txt"], {}, None),
        ("rpm", NfpmRpmPackageFieldSet, [], {}, ["contents/extra-file.txt"], {}, None),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            [],
            {},
            ["contents/extra-file.txt"],
            {"ghost_contents": ["/var/log/pkg.log"]},
            None,
        ),
        # with dependencies
        (
            "apk",
            NfpmApkPackageFieldSet,
            [
                "contents:files",
                "contents:file",
                "contents:symlinks",
                "contents:symlink",
                "contents:dirs",
                "contents:dir",
            ],
            {"postinstall": "scripts/postinstall.sh", "postupgrade": "scripts/apk-postupgrade.sh"},
            [
                "contents/sandbox-file.txt",
                "contents/some-executable",
                "scripts/postinstall.sh",
                "scripts/apk-postupgrade.sh",
            ],
            {},
            None,
        ),
        (
            "archlinux",
            NfpmArchlinuxPackageFieldSet,
            [
                "contents:files",
                "contents:file",
                "contents:symlinks",
                "contents:symlink",
                "contents:dirs",
                "contents:dir",
            ],
            {"postinstall": "scripts/postinstall.sh", "postupgrade": "scripts/arch-postupgrade.sh"},
            [
                "contents/sandbox-file.txt",
                "contents/some-executable",
                "scripts/postinstall.sh",
                "scripts/arch-postupgrade.sh",
            ],
            {},
            None,
        ),
        (
            "deb",
            NfpmDebPackageFieldSet,
            [
                "contents:files",
                "contents:file",
                "contents:symlinks",
                "contents:symlink",
                "contents:dirs",
                "contents:dir",
            ],
            {"postinstall": "scripts/postinstall.sh", "config": "scripts/deb-config.sh"},
            [
                "contents/sandbox-file.txt",
                "contents/some-executable",
                "scripts/postinstall.sh",
                "scripts/deb-config.sh",
            ],
            {},
            None,
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            [
                "contents:files",
                "contents:file",
                "contents:symlinks",
                "contents:symlink",
                "contents:dirs",
                "contents:dir",
            ],
            {"postinstall": "scripts/postinstall.sh", "verify": "scripts/rpm-verify.sh"},
            [
                "contents/sandbox-file.txt",
                "contents/some-executable",
                "scripts/postinstall.sh",
                "scripts/rpm-verify.sh",
            ],
            {},
            None,
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            [
                "contents:files",
                "contents:file",
                "contents:symlinks",
                "contents:symlink",
                "contents:dirs",
                "contents:dir",
            ],
            {"postinstall": "scripts/postinstall.sh", "verify": "scripts/rpm-verify.sh"},
            [
                "contents/sandbox-file.txt",
                "contents/some-executable",
                "scripts/postinstall.sh",
                "scripts/rpm-verify.sh",
            ],
            {"ghost_contents": ["/var/log/pkg.log"]},
            None,
        ),
        # with malformed dependency
        (
            "apk",
            NfpmApkPackageFieldSet,
            ["contents:malformed"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "archlinux",
            NfpmArchlinuxPackageFieldSet,
            ["contents:malformed"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "deb",
            NfpmDebPackageFieldSet,
            ["contents:malformed"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            ["contents:malformed"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        # with dependency file missing from sandbox
        (
            "apk",
            NfpmApkPackageFieldSet,
            ["contents:files", "contents:file"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "archlinux",
            NfpmArchlinuxPackageFieldSet,
            ["contents:files", "contents:file"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "deb",
            NfpmDebPackageFieldSet,
            ["contents:files", "contents:file"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            ["contents:files", "contents:file"],
            {},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        # with script file missing from sandbox
        (
            "apk",
            NfpmApkPackageFieldSet,
            [],
            {"postinstall": "scripts/postinstall.sh", "postupgrade": "scripts/apk-postupgrade.sh"},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "archlinux",
            NfpmArchlinuxPackageFieldSet,
            [],
            {"postinstall": "scripts/postinstall.sh", "postupgrade": "scripts/arch-postupgrade.sh"},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "deb",
            NfpmDebPackageFieldSet,
            [],
            {"postinstall": "scripts/postinstall.sh", "config": "scripts/deb-config.sh"},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            [],
            {"postinstall": "scripts/postinstall.sh", "verify": "scripts/rpm-verify.sh"},
            [],
            {},
            pytest.raises(ExecutionError),
        ),
    ),
)
def test_generate_nfpm_yaml(
    rule_runner: RuleRunner,
    packager: str,
    field_set_type: type[NfpmPackageFieldSet],
    dependencies: list[str],
    scripts: dict[str, str],
    content_sandbox_files: list[str],
    extra_metadata: dict[str, Any],
    expect_raise: ContextManager | None,
):
    content_sandbox_digest = get_digest(rule_runner, {path: "" for path in content_sandbox_files})

    description = f"A {packager} package"
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""
                nfpm_{packager}_package(
                    name="{_PKG_NAME}",
                    description="{description}",
                    package_name="{_PKG_NAME}",
                    version="{_PKG_VERSION}",
                    {'' if packager != 'deb' else 'maintainer="Foo Bar <deb@example.com>",'}
                    dependencies={repr(dependencies)},
                    scripts={repr(scripts)},
                    **{extra_metadata},
                )
                """
            ),
            "contents/BUILD": dedent(
                f"""
                file(
                    name="unrelated_file",
                    source="should.not.be.in.digest.txt",
                )
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
                nfpm_content_file(
                    name="malformed",  # needs either source or src.
                    dst="/usr/bin/foo",
                    file_mode=0o440,
                )
                """
            ),
            "contents/sandbox-file.txt": "",
            "contents/some-executable": "",
            "scripts/BUILD": dedent(
                """
                files(
                    name="scripts",
                    sources=["*", "!BUILD"],
                )
                """
            ),
            **{
                path: ""
                for path in [
                    "scripts/postinstall.sh",
                    "scripts/apk-postupgrade.sh",
                    "scripts/arch-postupgrade.sh",
                    "scripts/deb-config.sh",
                    "scripts/rpm-verify.sh",
                ]
            },
        }
    )
    target = rule_runner.get_target(Address("", target_name=_PKG_NAME))
    field_set = field_set_type.create(target)

    with cast(ContextManager, no_exception()) if expect_raise is None else expect_raise:
        result = rule_runner.request(
            NfpmPackageConfig,
            (
                NfpmPackageConfigRequest(
                    field_set=field_set, content_sandbox_digest=content_sandbox_digest
                ),
            ),
        )

    if expect_raise is not None:
        # error was raised, nothing else to check
        return

    # should always include nfpm.yaml
    assert result.digest != EMPTY_DIGEST
    digest_contents = rule_runner.request(DigestContents, (result.digest,))
    assert len(digest_contents) == 1
    nfpm_yaml_content = digest_contents[0]
    assert nfpm_yaml_content.path == "nfpm.yaml"

    # make sure it is valid yaml
    nfpm_yaml_content_string = nfpm_yaml_content.content.decode("utf-8")
    assert nfpm_yaml_content_string.startswith("# Generated by Pantsbuild\n")
    nfpm_yaml: dict[str, Any] = yaml.safe_load(nfpm_yaml_content_string)
    assert isinstance(nfpm_yaml, dict)

    for key in ("disable_globbing", "contents", "mtime"):
        assert key in nfpm_yaml
    assert nfpm_yaml["disable_globbing"] is True
    assert nfpm_yaml["mtime"]

    # only expected because description defined in this test's nfpm_*_package target
    assert "description" in nfpm_yaml
    assert description == nfpm_yaml["description"]

    contents: list[dict[str, Any]] = nfpm_yaml["contents"]
    assert isinstance(contents, list)
    for entry in contents:
        assert isinstance(entry, dict)  # NfpmContent is a TypedDict
        assert "type" in entry
        assert "dst" in entry
        assert "packager" not in entry  # an nFPM feature that we will not support and do not use
        entry_type = entry["type"]
        if entry_type not in ("dir", "ghost"):
            assert "src" in entry
        if entry_type != "ghost":
            assert "file_info" in entry
            file_info = entry["file_info"]
            assert isinstance(file_info, dict)  # NfpmFileInfo is a TypedDict
            for key in NfpmFileInfo.__annotations__:
                # though nFPM does not require it, we always specify all of these.
                assert key in file_info

    contents_by_dst = {entry["dst"]: entry for entry in contents}

    if "contents:files" in dependencies:
        dst = f"/usr/share/{_PKG_NAME}/{_PKG_NAME}.{_PKG_VERSION}/installed-file.txt"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "doc" == entry["type"]
        assert "contents/sandbox-file.txt" == entry["src"]
        assert 0o0644 == entry["file_info"]["mode"]

        dst = f"/etc/{_PKG_NAME}/installed-file.txt"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "config" == entry["type"]
        assert "contents/sandbox-file.txt" == entry["src"]
        assert "root" == entry["file_info"]["group"]
        assert 0o0600 == entry["file_info"]["mode"]

    if "contents:file" in dependencies:
        dst = "/usr/bin/some-executable"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "" == entry["type"]
        assert "contents/some-executable" == entry["src"]
        assert 0o0755 == entry["file_info"]["mode"]

    if "contents:symlinks" in dependencies:
        dst = "/usr/bin/new-relative-symlinked-exe"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "symlink" == entry["type"]
        assert "some-executable" == entry["src"]
        assert "special-group" == entry["file_info"]["group"]

        dst = "/usr/bin/new-absolute-symlinked-exe"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "symlink" == entry["type"]
        assert "/usr/bin/some-executable" == entry["src"]

    if "contents:symlink" in dependencies:
        dst = "/usr/sbin/sbin-executable"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "symlink" == entry["type"]
        assert "/usr/bin/some-executable" == entry["src"]

    if "contents:dirs" in dependencies:
        dst = f"/usr/share/{_PKG_NAME}"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "dir" == entry["type"]
        assert "special-group" == entry["file_info"]["group"]

    if "contents:dir" in dependencies:
        dst = f"/etc/{_PKG_NAME}"
        assert dst in contents_by_dst
        entry = contents_by_dst.pop(dst)
        assert "dir" == entry["type"]
        assert 0o0700 == entry["file_info"]["mode"]

    if "ghost_contents" in extra_metadata:
        for dst in extra_metadata["ghost_contents"]:
            assert dst in contents_by_dst
            entry = contents_by_dst.pop(dst)
            assert "ghost" == entry["type"]

    # make sure all contents have been accounted for (popped off above)
    assert len(contents_by_dst) == 0

    if not scripts:
        assert "scripts" not in nfpm_yaml
    for script_type, script_path in scripts.items():
        value: dict[str, Any] | str = nfpm_yaml
        for key in field_set.scripts.nfpm_aliases[script_type].split("."):
            assert isinstance(value, dict)
            assert key in value
            value = value[key]
        assert isinstance(value, str)
        assert value == script_path
