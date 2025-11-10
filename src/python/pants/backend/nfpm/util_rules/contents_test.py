# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.nfpm.dependency_inference import rules as nfpm_dependency_inference_rules
from pants.backend.nfpm.field_sets import NFPM_CONTENT_FIELD_SET_TYPES, NfpmContentFieldSet
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_types_rules
from pants.backend.nfpm.util_rules.contents import (
    GetPackageFieldSetsForNfpmContentFileDepsRequest,
    PackageFieldSetsForNfpmContentFileDeps,
)
from pants.backend.nfpm.util_rules.contents import rules as nfpm_contents_rules
from pants.backend.nfpm.util_rules.generate_config import rules as nfpm_generate_config_rules
from pants.backend.nfpm.util_rules.inject_config import rules as nfpm_inject_config_rules
from pants.core.target_types import ArchiveFieldSet, ArchiveTarget, FilesGeneratorTarget, FileTarget
from pants.core.target_types import rules as core_target_type_rules
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner

_PKG_NAME = "pkg"
_PKG_VERSION = "3.2.1"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            ArchiveTarget,
            FileTarget,
            FilesGeneratorTarget,
            *nfpm_target_types(),
        ],
        rules=[
            *core_target_type_rules(),
            *nfpm_target_types_rules(),
            *nfpm_dependency_inference_rules(),
            *nfpm_generate_config_rules(),
            *nfpm_inject_config_rules(),
            *nfpm_contents_rules(),
            *(
                UnionRule(NfpmContentFieldSet, field_set_type)
                for field_set_type in NFPM_CONTENT_FIELD_SET_TYPES
            ),
            QueryRule(
                PackageFieldSetsForNfpmContentFileDeps,
                (GetPackageFieldSetsForNfpmContentFileDepsRequest,),
            ),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


@pytest.mark.parametrize(
    ("packager",),
    (
        ("apk",),
        ("archlinux",),
        ("deb",),
        ("rpm",),
    ),
)
def test_get_package_field_sets_for_nfpm_content_file_deps(rule_runner: RuleRunner, packager: str):
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
                    {"" if packager != "deb" else 'maintainer="Foo Bar <deb@example.com>",'}
                    dependencies=[
                        "contents:files",
                        "contents:file",
                        "package:package",
                        "package:output_path_package",
                    ],
                )
                """
            ),
            "package/BUILD": dedent(
                """
                file(
                    name="file",
                    source="archive-contents.txt",
                )
                archive(
                    name="archive",
                    format="tar",
                    files=[":file"],
                )
                nfpm_content_file(
                    name="package",
                    src="archive.tar",
                    dst="/opt/foo/archive.tar",
                    dependencies=[":archive"],
                )
                archive(
                    name="output_path_archive",
                    format="tar",
                    output_path="relative_to_build_root.tar",
                    files=[":file"],
                )
                nfpm_content_file(
                    name="output_path_package",
                    src="relative_to_build_root.tar",
                    dst="/opt/foo/relative_to_build_root.tar",
                    dependencies=[":output_path_archive"],
                )
                """
            ),
            "package/archive-contents.txt": "",
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
                )
                nfpm_content_file(
                    name="file",
                    source="some-executable",
                    dst="/usr/bin/some-executable",
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
    address = Address("", target_name=_PKG_NAME)

    result = rule_runner.request(
        PackageFieldSetsForNfpmContentFileDeps,
        [
            GetPackageFieldSetsForNfpmContentFileDepsRequest([address], [ArchiveFieldSet]),
        ],
    )

    content_file_tgts = result.nfpm_content_file_targets.roots
    assert len(content_file_tgts) == 5
    assert {tgt.address for tgt in content_file_tgts} == {
        Address("package", target_name="package"),
        Address("package", target_name="output_path_package"),
        Address("contents", target_name="file"),
        Address("contents", target_name="files", generated_name="/etc/pkg/installed-file.txt"),
        Address(
            "contents",
            target_name="files",
            generated_name="/usr/share/pkg/pkg.3.2.1/installed-file.txt",
        ),
    }

    content_file_deps = result.nfpm_content_file_targets.dependencies
    assert len(content_file_deps) == 3
    assert {tgt.address for tgt in content_file_deps} == {
        Address("package", target_name="archive"),
        Address("package", target_name="output_path_archive"),
        Address("contents", target_name="sandbox_file"),
    }

    pkg_field_sets = result.package_field_sets
    assert len(pkg_field_sets.collection) == 2
    assert [len(collection) for collection in pkg_field_sets.collection] == [1, 1]

    assert len(pkg_field_sets.field_sets) == 2
    assert {tgt.address for tgt in pkg_field_sets.field_sets} == {
        Address("package", target_name="archive"),
        Address("package", target_name="output_path_archive"),
    }
