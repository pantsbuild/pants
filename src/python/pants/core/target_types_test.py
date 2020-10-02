# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import tarfile
import zipfile
from io import BytesIO
from textwrap import dedent

from pants.backend.python.goals import package_python_binary
from pants.backend.python.target_types import PythonBinary
from pants.backend.python.util_rules import pex_from_targets
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import (
    ArchiveFieldSet,
    ArchiveTarget,
    Files,
    FilesSources,
    RelocatedFiles,
    RelocateFilesViaCodegenRequest,
)
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents, FileContent
from pants.engine.target import GeneratedSources, Sources, TransitiveTargets
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_relocated_files() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_type_rules(),
            *source_files_rules(),
            QueryRule(GeneratedSources, [RelocateFilesViaCodegenRequest]),
            QueryRule(TransitiveTargets, [Addresses]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[Files, RelocatedFiles],
    )

    def assert_prefix_mapping(
        *,
        original: str,
        src: str,
        dest: str,
        expected: str,
    ) -> None:
        rule_runner.create_file(original)
        rule_runner.add_to_build_file(
            "",
            dedent(
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
            overwrite=True,
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
        transitive_targets = rule_runner.request(TransitiveTargets, [Addresses([tgt.address])])
        all_sources = rule_runner.request(
            SourceFiles,
            [
                SourceFilesRequest(
                    (tgt.get(Sources) for tgt in transitive_targets.closure),
                    enable_codegen=True,
                    for_sources_types=(FilesSources,),
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
            *package_python_binary.rules(),
            QueryRule(BuiltPackage, [ArchiveFieldSet]),
        ],
        target_types=[ArchiveTarget, Files, RelocatedFiles, PythonBinary],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python", "--no-pants-distdir-legacy-paths"]
    )

    rule_runner.create_file("resources/d1.json", "{'k': 1}")
    rule_runner.create_file("resources/d2.json", "{'k': 2}")
    rule_runner.add_to_build_file(
        "resources",
        dedent(
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
    )

    rule_runner.create_file("project/app.py", "print('hello world!')")
    rule_runner.add_to_build_file("project", "python_binary(sources=['app.py'])")

    rule_runner.add_to_build_file(
        "",
        dedent(
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
            )
            """
        ),
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
    io = BytesIO()
    io.write(archive2)
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
