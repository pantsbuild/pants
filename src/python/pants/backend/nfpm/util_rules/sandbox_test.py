# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from textwrap import dedent
from typing import ContextManager, cast

import pytest

from pants.backend.nfpm.dependency_inference import rules as nfpm_dependency_inference_rules
from pants.backend.nfpm.field_sets import (
    NfpmDebPackageFieldSet,
    NfpmPackageFieldSet,
    NfpmRpmPackageFieldSet,
)
from pants.backend.nfpm.target_types import (
    NfpmContentDir,
    NfpmContentFile,
    NfpmContentFiles,
    NfpmContentSymlink,
    NfpmDebPackage,
    NfpmRpmPackage,
)
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_types_rules
from pants.backend.nfpm.util_rules.sandbox import (
    NfpmContentSandbox,
    NfpmContentSandboxRequest,
    _DepCategory,
)
from pants.backend.nfpm.util_rules.sandbox import rules as nfpm_sandbox_rules
from pants.core.target_types import (
    ArchiveTarget,
    FilesGeneratorTarget,
    FileSourceField,
    FileTarget,
    GenericTarget,
    ResourceTarget,
)
from pants.core.target_types import rules as core_target_type_rules
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, DigestContents, DigestEntries
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.selectors import Get
from pants.engine.rules import QueryRule, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, SingleSourceField, Target
from pants.engine.unions import UnionRule
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import RuleRunner

# _NfpmSortedDeps.sort(...)

_PKG_NAME = "pkg"
_PKG_VERSION = "3.2.1"

_A = Address("", target_name="t")
_DEB_PKG = NfpmDebPackage(
    {"package_name": _PKG_NAME, "version": _PKG_VERSION, "maintainer": "Foo Bar <baz@example.com>"},
    _A,
)
_RPM_PKG = NfpmRpmPackage({"package_name": _PKG_NAME, "version": _PKG_VERSION}, _A)


@pytest.mark.parametrize(
    "tgt,field_set_type,expected",
    (
        (NfpmContentDir({"dst": "/foo"}, _A), NfpmPackageFieldSet, _DepCategory.ignore),
        (
            NfpmContentSymlink({"dst": "/foo", "src": "/bar"}, _A),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.ignore,
        ),
        (
            NfpmContentFile({"dst": "/foo", "src": "bar", "dependencies": [":bar"]}, _A),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.nfpm_content_from_dependency,
        ),
        (
            NfpmContentFile({"dst": "/foo", "source": "bar"}, _A),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.nfpm_content_from_source,
        ),
        (_DEB_PKG, NfpmDebPackageFieldSet, _DepCategory.nfpm_package),
        (_DEB_PKG, NfpmRpmPackageFieldSet, _DepCategory.ignore),
        (_RPM_PKG, NfpmDebPackageFieldSet, _DepCategory.ignore),
        (_RPM_PKG, NfpmRpmPackageFieldSet, _DepCategory.nfpm_package),
        (GenericTarget({}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
        (FileTarget({"source": "foo"}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
        (ResourceTarget({"source": "foo"}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
        (ArchiveTarget({"format": "zip"}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
    ),
)
def test_dep_category_for_target(
    tgt: Target, field_set_type: type[NfpmPackageFieldSet], expected: _DepCategory
):
    category = _DepCategory.for_target(tgt, field_set_type)
    assert category == expected


class MockCodegenSourceField(SingleSourceField):
    pass


class MockCodegenTarget(Target):
    alias = "codegen_target"
    core_fields = (MockCodegenSourceField,)
    help = "n/a"


class MockCodegenGenerateSourcesRequest(GenerateSourcesRequest):
    input = MockCodegenSourceField
    output = FileSourceField


@rule
async def do_codegen(request: MockCodegenGenerateSourcesRequest) -> GeneratedSources:
    # Generate a file with the same contents as each input file.
    input_files = await Get(DigestContents, Digest, request.protocol_sources.digest)
    generated_files = [
        dataclasses.replace(input_file, path=input_file.path + ".generated")
        for input_file in input_files
    ]
    result = await Get(Snapshot, CreateDigest(generated_files))
    return GeneratedSources(result)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            ArchiveTarget,
            FileTarget,
            FilesGeneratorTarget,
            NfpmDebPackage,
            NfpmRpmPackage,
            NfpmContentFile,
            NfpmContentFiles,
            MockCodegenTarget,
        ],
        rules=[
            *core_target_type_rules(),
            *nfpm_target_types_rules(),
            *nfpm_dependency_inference_rules(),
            *nfpm_sandbox_rules(),
            QueryRule(NfpmContentSandbox, (NfpmContentSandboxRequest,)),
            QueryRule(DigestEntries, (Digest,)),
            do_codegen,
            UnionRule(GenerateSourcesRequest, MockCodegenGenerateSourcesRequest),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


@pytest.mark.parametrize(
    "packager,field_set_type,dependencies,scripts,expected",
    (
        # empty digest
        ("deb", NfpmDebPackageFieldSet, [], {}, set()),
        ("rpm", NfpmRpmPackageFieldSet, [], {}, set()),
        # non-empty digest
        (
            "deb",
            NfpmDebPackageFieldSet,
            ["contents:files", "contents:file"],
            {"postinstall": "scripts/postinstall.sh", "config": "scripts/deb-config.sh"},
            {
                "contents/sandbox-file.txt",
                "contents/some-executable",
                "scripts/postinstall.sh",
                "scripts/deb-config.sh",
            },
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            ["contents:files", "contents:file"],
            {"postinstall": "scripts/postinstall.sh", "verify": "scripts/rpm-verify.sh"},
            {
                "contents/sandbox-file.txt",
                "contents/some-executable",
                "scripts/postinstall.sh",
                "scripts/rpm-verify.sh",
            },
        ),
        # dependency on file w/o intermediate nfpm_content_file target
        # should have the file in the sandbox, though config won't include it.
        (
            "deb",
            NfpmDebPackageFieldSet,
            ["contents/sandbox-file.txt:sandbox_file"],
            {},
            {"contents/sandbox-file.txt"},
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            ["contents/sandbox-file.txt:sandbox_file"],
            {},
            {"contents/sandbox-file.txt"},
        ),
        # codegen & package build
        (
            "deb",
            NfpmDebPackageFieldSet,
            ["codegen:generated", "contents:files", "package:package"],
            {},
            {
                "codegen/foobar.codegen.generated",
                "contents/sandbox-file.txt",
                "package/archive.tar",
            },
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            ["codegen:generated", "contents:files", "package:package"],
            {},
            {
                "codegen/foobar.codegen.generated",
                "contents/sandbox-file.txt",
                "package/archive.tar",
            },
        ),
        # error finding script
        (
            "deb",
            NfpmDebPackageFieldSet,
            ["contents:files", "contents:file"],
            {"postinstall": "scripts/missing.sh"},
            pytest.raises(ExecutionError),
        ),
        (
            "rpm",
            NfpmRpmPackageFieldSet,
            ["contents:files", "contents:file"],
            {"postinstall": "scripts/missing.sh"},
            pytest.raises(ExecutionError),
        ),
    ),
)
def test_populate_nfpm_content_sandbox(
    rule_runner: RuleRunner,
    packager: str,
    field_set_type: type[NfpmPackageFieldSet],
    dependencies: list[str],
    scripts: dict[str, str],
    expected: set[str] | ContextManager,
):
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""
                nfpm_{packager}_package(
                    name="{_PKG_NAME}",
                    package_name="{_PKG_NAME}",
                    version="{_PKG_VERSION}",
                    {'' if packager != 'deb' else 'maintainer="Foo Bar <deb@example.com>",'}
                    dependencies={repr(dependencies)},
                    scripts={repr(scripts)},
                )
                """
            ),
            "codegen/BUILD": dedent(
                """
                codegen_target(
                    source="./foobar.codegen",
                )
                nfpm_content_file(
                    name="generated",
                    src="foobar.codegen.generated",
                    dst="/usr/lib/foobar.codegen.generated",
                    dependencies=["./foobar.codegen"],
                )
                """
            ),
            "codegen/foobar.codegen": "",
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
                    "scripts/deb-config.sh",
                    "scripts/rpm-verify.sh",
                ]
            },
        }
    )

    target = rule_runner.get_target(Address("", target_name=_PKG_NAME))

    with cast(ContextManager, no_exception()) if isinstance(expected, set) else expected:
        result = rule_runner.request(
            NfpmContentSandbox,
            [
                NfpmContentSandboxRequest(field_set=field_set_type.create(target)),
            ],
        )

    if not isinstance(expected, set):
        # error was raised, nothing else to check
        return

    if not expected:
        assert result.digest == EMPTY_DIGEST
        return

    digest_entries = rule_runner.request(DigestEntries, (result.digest,))
    paths = {entry.path for entry in digest_entries}
    assert paths == expected
