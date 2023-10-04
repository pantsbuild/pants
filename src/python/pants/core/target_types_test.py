# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import tarfile
import textwrap
import zipfile
from io import BytesIO
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules as python_target_type_rules
from pants.backend.python.goals import package_pex_binary, run_pex_binary
from pants.backend.python.target_types import PexBinary, PythonSourceTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.core.goals import run
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import (
    ArchiveFieldSet,
    ArchiveTarget,
    FilesGeneratorTarget,
    FileSourceField,
    FileTarget,
    LockfilesGeneratorSourcesField,
    LockfileSourceField,
    RelocatedFiles,
    RelocateFilesViaCodegenRequest,
    ResourceTarget,
    http_source,
    per_platform,
)
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules import archive, source_files, system_binaries
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents, FileContent, GlobMatchErrorBehavior
from pants.engine.platform import Platform
from pants.engine.target import (
    GeneratedSources,
    SourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.option.global_options import UnmatchedBuildFileGlobs
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule, mock_console


def test_relocated_files() -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            *target_type_rules(),
            *archive.rules(),
            *source_files.rules(),
            *system_binaries.rules(),
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
    rule_runner = PythonRuleRunner(
        rules=[
            *target_type_rules(),
            *archive.rules(),
            *source_files.rules(),
            *system_binaries.rules(),
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

    rule_runner = PythonRuleRunner(
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


@pytest.mark.parametrize("use_per_platform", [True, False])
def test_url_assets(use_per_platform: bool) -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            *target_type_rules(),
            *pex_from_targets.rules(),
            *package_pex_binary.rules(),
            *run_pex_binary.rules(),
            *python_target_type_rules.rules(),
            *run.rules(),
        ],
        target_types=[FileTarget, ResourceTarget, PythonSourceTarget, PexBinary],
        objects={"http_source": http_source, "per_platform": per_platform},
    )
    http_source_info = (
        'url="https://raw.githubusercontent.com/python/cpython/7e46ae33bd522cf8331052c3c8835f9366599d8d/Lib/antigravity.py",'
        + "len=500,"
        + 'sha256="8a5ee63e1b79ba2733e7ff4290b6eefea60e7f3a1ccb6bb519535aaf92b44967"'
    )

    def source_field_value(http_source_value: str) -> str:
        if use_per_platform:
            return f"per_platform({Platform.create_for_localhost().value}={http_source_value})"
        return http_source_value

    rule_runner.write_files(
        {
            "assets/BUILD": dedent(
                f"""\
                resource(
                    name='antigravity',
                    source={source_field_value(f'http_source({http_source_info})')}
                )
                resource(
                    name='antigravity_renamed',
                    source={source_field_value(f'http_source({http_source_info}, filename="antigravity_renamed.py")')}
                )
                """
            ),
            "app/app.py": textwrap.dedent(
                """\
                import pathlib

                assets_path = pathlib.Path(__file__).parent.parent / "assets"
                for path in assets_path.iterdir():
                    print(path.name)
                    assert "https://xkcd.com/353/" in path.read_text()
                """
            ),
            "app/BUILD": textwrap.dedent(
                """\
                python_source(
                    source="app.py",
                    dependencies=[
                        "assets:antigravity",
                        "assets:antigravity_renamed",
                    ]
                )
                pex_binary(name="app.py", entry_point='app.py')
                """
            ),
        }
    )
    with mock_console(rule_runner.options_bootstrapper) as (console, stdout_reader):
        rule_runner.run_goal_rule(
            run.Run,
            args=[
                "app:app.py",
            ],
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )
        stdout = stdout_reader.get_stdout()
        assert "antigravity.py" in stdout
        assert "antigravity_renamed.py" in stdout


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://foo/bar", "bar"),
        ("http://foo/bar.baz", "bar.baz"),
        ("http://foo/bar.baz?query=yes/no", "bar.baz"),
        ("http://foo/bar/baz/file.ext", "file.ext"),
        ("www.foo.bar", "www.foo.bar"),
        ("www.foo.bar?query=yes/no", "www.foo.bar"),
    ],
)
def test_http_source_filename(url, expected):
    assert http_source(url, len=0, sha256="").filename == expected


@pytest.mark.parametrize(
    "kwargs, exc_match",
    [
        (
            dict(url=None, len=0, sha256=""),
            pytest.raises(TypeError, match=r"`url` must be a `str`"),
        ),
        (
            dict(url="http://foo/bar", len="", sha256=""),
            pytest.raises(TypeError, match=r"`len` must be a `int`"),
        ),
        (
            dict(url="http://foo/bar", len=0, sha256=123),
            pytest.raises(TypeError, match=r"`sha256` must be a `str`"),
        ),
        (
            dict(url="http://foo/bar", len=0, sha256="", filename=10),
            pytest.raises(TypeError, match=r"`filename` must be a `str`"),
        ),
        (
            dict(url="http://foo/bar/", len=0, sha256=""),
            pytest.raises(ValueError, match=r"Couldn't deduce filename"),
        ),
        (
            dict(url="http://foo/bar/", len=0, sha256="", filename="../foobar.txt"),
            pytest.raises(ValueError, match=r"`filename` cannot contain a path separator."),
        ),
    ],
)
def test_invalid_http_source(kwargs, exc_match):
    with exc_match:
        http_source(**kwargs)


@pytest.mark.parametrize(
    "error_behavior", [GlobMatchErrorBehavior.warn, GlobMatchErrorBehavior.error]
)
def test_lockfile_glob_match_error_behavior(
    error_behavior: GlobMatchErrorBehavior,
) -> None:
    lockfile_source = LockfileSourceField("test.lock", Address("", target_name="lockfile-test"))
    assert (
        GlobMatchErrorBehavior.ignore
        == lockfile_source.path_globs(
            UnmatchedBuildFileGlobs(error_behavior)
        ).glob_match_error_behavior
    )


@pytest.mark.parametrize(
    "error_behavior", [GlobMatchErrorBehavior.warn, GlobMatchErrorBehavior.error]
)
def test_lockfiles_glob_match_error_behavior(
    error_behavior: GlobMatchErrorBehavior,
) -> None:
    lockfile_sources = LockfilesGeneratorSourcesField(
        ["test.lock"], Address("", target_name="lockfiles-test")
    )
    assert (
        GlobMatchErrorBehavior.ignore
        == lockfile_sources.path_globs(
            UnmatchedBuildFileGlobs(error_behavior)
        ).glob_match_error_behavior
    )
