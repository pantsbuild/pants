# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import tarfile
import zipfile
from io import BytesIO
from textwrap import dedent

from pants.backend.python import target_types_rules as python_target_type_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules import pex_from_targets
from pants.core import target_types as core_target_types
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import (
    ArchiveFieldSet,
    ArchiveTarget,
    FilesGeneratorTarget,
    FileSourceField,
    FileTarget,
    GenerateTargetsFromFiles,
    GenerateTargetsFromResources,
    RelocatedFiles,
    RelocateFilesViaCodegenRequest,
    ResourcesGeneratorTarget,
    ResourceTarget,
)
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules.archive import rules as archive_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents, FileContent
from pants.engine.target import (
    GeneratedSources,
    GeneratedTargets,
    SingleSourceField,
    SourcesField,
    Tags,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_relocated_files() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_type_rules(),
            *archive_rules(),
            *source_files_rules(),
            QueryRule(GeneratedSources, [RelocateFilesViaCodegenRequest]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[FilesGeneratorTarget, RelocatedFiles],
    )

    def assert_prefix_mapping(
        *,
        original: str,
        src: str,
        dest: str,
        expected: str,
    ) -> None:
        rule_runner.write_files(
            {
                original: "",
                "BUILD": dedent(
                    f"""\
                    files(name="original", sources=[{repr(original)}])

                    relocated_files(
                        name="relocated",
                        files_targets=[":original"],
                        src={repr(src)},
                        dest={repr(dest)},
                    )
                    """
                ),
            }
        )

        tgt = rule_runner.get_target(Address("", target_name="relocated"))
        result = rule_runner.request(
            GeneratedSources, [RelocateFilesViaCodegenRequest(EMPTY_SNAPSHOT, tgt)]
        )
        assert result.snapshot.files == (expected,)

        # We also ensure that when looking at the transitive dependencies of the `relocated_files`
        # target and then getting all the code of that closure, we only end up with the relocated
        # files. If we naively marked the original files targets as a typical `Dependencies` field,
        # we would hit this issue.
        transitive_targets = rule_runner.request(
            TransitiveTargets, [TransitiveTargetsRequest([tgt.address])]
        )
        all_sources = rule_runner.request(
            SourceFiles,
            [
                SourceFilesRequest(
                    (tgt.get(SourcesField) for tgt in transitive_targets.closure),
                    enable_codegen=True,
                    for_sources_types=(FileSourceField,),
                )
            ],
        )
        assert all_sources.snapshot.files == (expected,)

    # No-op.
    assert_prefix_mapping(original="old_prefix/f.ext", src="", dest="", expected="old_prefix/f.ext")
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="old_prefix",
        dest="old_prefix",
        expected="old_prefix/f.ext",
    )

    # Remove prefix.
    assert_prefix_mapping(original="old_prefix/f.ext", src="old_prefix", dest="", expected="f.ext")
    assert_prefix_mapping(
        original="old_prefix/subdir/f.ext", src="old_prefix", dest="", expected="subdir/f.ext"
    )

    # Add prefix.
    assert_prefix_mapping(original="f.ext", src="", dest="new_prefix", expected="new_prefix/f.ext")
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="",
        dest="new_prefix",
        expected="new_prefix/old_prefix/f.ext",
    )

    # Replace prefix.
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="old_prefix",
        dest="new_prefix",
        expected="new_prefix/f.ext",
    )
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="old_prefix",
        dest="new_prefix/subdir",
        expected="new_prefix/subdir/f.ext",
    )

    # Replace prefix, but preserve a common start.
    assert_prefix_mapping(
        original="common_prefix/foo/f.ext",
        src="common_prefix/foo",
        dest="common_prefix/bar",
        expected="common_prefix/bar/f.ext",
    )
    assert_prefix_mapping(
        original="common_prefix/subdir/f.ext",
        src="common_prefix/subdir",
        dest="common_prefix",
        expected="common_prefix/f.ext",
    )


def test_relocated_relocated_files() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_type_rules(),
            QueryRule(GeneratedSources, [RelocateFilesViaCodegenRequest]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[FilesGeneratorTarget, RelocatedFiles],
    )

    rule_runner.write_files(
        {
            "original_prefix/file.txt": "",
            "BUILD": dedent(
                """\
                files(name="original", sources=["original_prefix/file.txt"])

                relocated_files(
                    name="relocated",
                    files_targets=[":original"],
                    src="original_prefix",
                    dest="intermediate_prefix",
                )

                relocated_files(
                    name="double_relocated",
                    files_targets=[":relocated"],
                    src="intermediate_prefix",
                    dest="final_prefix",
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="double_relocated"))
    result = rule_runner.request(
        GeneratedSources, [RelocateFilesViaCodegenRequest(EMPTY_SNAPSHOT, tgt)]
    )
    assert result.snapshot.files == ("final_prefix/file.txt",)


def test_archive() -> None:
    """Integration test for the `archive` target type.

    This tests some edges:
    * Using both `files` and `relocated_files`.
    * An `archive` containing another `archive`.
    """

    rule_runner = RuleRunner(
        rules=[
            *target_type_rules(),
            *pex_from_targets.rules(),
            *package_pex_binary.rules(),
            *python_target_type_rules.rules(),
            QueryRule(BuiltPackage, [ArchiveFieldSet]),
        ],
        target_types=[ArchiveTarget, FilesGeneratorTarget, RelocatedFiles, PexBinary],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})

    rule_runner.write_files(
        {
            "resources/d1.json": "{'k': 1}",
            "resources/d2.json": "{'k': 2}",
            "resources/BUILD": dedent(
                """\
                files(name='original_files', sources=['*.json'])

                relocated_files(
                    name='relocated_files',
                    files_targets=[':original_files'],
                    src="resources",
                    dest="data",
                )
                """
            ),
            "project/app.py": "print('hello world!')",
            "project/BUILD": "pex_binary(entry_point='app.py')",
            "BUILD": dedent(
                """\
                archive(
                    name="archive1",
                    packages=["project"],
                    files=["resources:original_files"],
                    format="zip",
                )

                archive(
                    name="archive2",
                    packages=[":archive1"],
                    files=["resources:relocated_files"],
                    format="tar",
                    output_path="output/archive2.tar",
                )
                """
            ),
        }
    )

    def get_archive(target_name: str) -> FileContent:
        tgt = rule_runner.get_target(Address("", target_name=target_name))
        built_package = rule_runner.request(BuiltPackage, [ArchiveFieldSet.create(tgt)])
        digest_contents = rule_runner.request(DigestContents, [built_package.digest])
        assert len(digest_contents) == 1
        return digest_contents[0]

    def assert_archive1_is_valid(zip_bytes: bytes) -> None:
        io = BytesIO()
        io.write(zip_bytes)
        with zipfile.ZipFile(io) as zf:
            assert set(zf.namelist()) == {
                "resources/d1.json",
                "resources/d2.json",
                "project/project.pex",
            }
            with zf.open("resources/d1.json", "r") as f:
                assert f.read() == b"{'k': 1}"
            with zf.open("resources/d2.json", "r") as f:
                assert f.read() == b"{'k': 2}"

    archive1 = get_archive("archive1")
    assert_archive1_is_valid(archive1.content)

    archive2 = get_archive("archive2")
    assert archive2.path == "output/archive2.tar"
    io = BytesIO()
    io.write(archive2.content)
    io.seek(0)
    with tarfile.open(fileobj=io, mode="r:") as tf:
        assert set(tf.getnames()) == {"data/d1.json", "data/d2.json", "archive1.zip"}

        def get_file(fp: str) -> bytes:
            reader = tf.extractfile(fp)
            assert reader is not None
            return reader.read()

        assert get_file("data/d1.json") == b"{'k': 1}"
        assert get_file("data/d2.json") == b"{'k': 2}"
        assert_archive1_is_valid(get_file("archive1.zip"))


def test_generate_file_and_resource_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            core_target_types.generate_targets_from_files,
            core_target_types.generate_targets_from_resources,
            QueryRule(GeneratedTargets, [GenerateTargetsFromFiles]),
            QueryRule(GeneratedTargets, [GenerateTargetsFromResources]),
        ],
        target_types=[FilesGeneratorTarget, ResourcesGeneratorTarget],
    )
    rule_runner.write_files(
        {
            "assets/BUILD": dedent(
                """\
                files(
                    name='files',
                    sources=['**/*.ext'],
                    overrides={'f1.ext': {'tags': ['overridden']}},
                )

                resources(
                    name='resources',
                    sources=['**/*.ext'],
                    overrides={'f1.ext': {'tags': ['overridden']}},
                )
                """
            ),
            "assets/f1.ext": "",
            "assets/f2.ext": "",
            "assets/subdir/f.ext": "",
        }
    )

    files_generator = rule_runner.get_target(Address("assets", target_name="files"))
    resources_generator = rule_runner.get_target(Address("assets", target_name="resources"))

    def gen_file_tgt(rel_fp: str, tags: list[str] | None = None) -> FileTarget:
        return FileTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address("assets", target_name="files", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join("assets", rel_fp)),
        )

    def gen_resource_tgt(rel_fp: str, tags: list[str] | None = None) -> ResourceTarget:
        return ResourceTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address("assets", target_name="resources", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join("assets", rel_fp)),
        )

    generated_files = rule_runner.request(
        GeneratedTargets, [GenerateTargetsFromFiles(files_generator)]
    )
    generated_resources = rule_runner.request(
        GeneratedTargets, [GenerateTargetsFromResources(resources_generator)]
    )

    assert generated_files == GeneratedTargets(
        files_generator,
        {
            gen_file_tgt("f1.ext", tags=["overridden"]),
            gen_file_tgt("f2.ext"),
            gen_file_tgt("subdir/f.ext"),
        },
    )
    assert generated_resources == GeneratedTargets(
        resources_generator,
        {
            gen_resource_tgt("f1.ext", tags=["overridden"]),
            gen_resource_tgt("f2.ext"),
            gen_resource_tgt("subdir/f.ext"),
        },
    )
