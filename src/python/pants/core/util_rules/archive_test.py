# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import base64
import gzip
import subprocess
import tarfile
import zipfile
from io import BytesIO

import pytest

from pants.core.util_rules import archive, system_binaries
from pants.core.util_rules.archive import CreateArchive, ExtractedArchive
from pants.core.util_rules.system_binaries import ArchiveFormat
from pants.engine.fs import Digest, DigestContents, FileContent
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *archive.rules(),
            *system_binaries.rules(),
            QueryRule(Digest, [CreateArchive]),
            QueryRule(ExtractedArchive, [Digest]),
        ],
    )


FILES = {"foo": b"bar", "hello/world": b"Hello, World!"}
EXPECTED_DIGEST_CONTENTS = DigestContents(
    [FileContent(name, content) for name, content in FILES.items()]
)


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_extract_zip(rule_runner: RuleRunner, compression: int) -> None:
    io = BytesIO()
    with zipfile.ZipFile(io, "w", compression=compression) as zf:
        for name, content in FILES.items():
            zf.writestr(name, content)
    io.flush()
    input_snapshot = rule_runner.make_snapshot({"test.zip": io.getvalue()})

    extracted_archive = rule_runner.request(ExtractedArchive, [input_snapshot.digest])
    digest_contents = rule_runner.request(DigestContents, [extracted_archive.digest])
    assert digest_contents == EXPECTED_DIGEST_CONTENTS


@pytest.mark.parametrize("compression", ["", "gz", "bz2", "xz"])
def test_extract_tar(rule_runner: RuleRunner, compression: str) -> None:
    io = BytesIO()
    mode = f"w:{compression}" if compression else "w"
    with tarfile.open(mode=mode, fileobj=io) as tf:
        for name, content in FILES.items():
            tarinfo = tarfile.TarInfo(name)
            tarinfo.size = len(content)
            tf.addfile(tarinfo, BytesIO(content))
    ext = f"tar.{compression}" if compression else "tar"
    input_snapshot = rule_runner.make_snapshot({f"test.{ext}": io.getvalue()})

    extracted_archive = rule_runner.request(ExtractedArchive, [input_snapshot.digest])
    digest_contents = rule_runner.request(DigestContents, [extracted_archive.digest])
    assert digest_contents == EXPECTED_DIGEST_CONTENTS


def test_extract_tarlz4(rule_runner: RuleRunner):
    if subprocess.run(["lz4", "--help"], check=False).returncode != 0:
        pytest.skip(reason="lz4 not on PATH")

    archive_content = base64.b64decode(
        b"BCJNGGRAp9MAAACfdG1wL21zZy8AAQBI+AAwMDAwNzc1ADAwMDE3NTEIAAQCAP8HADE0MjMxNTUzMjAxADAxNDQwM"
        b"gAgNZQASAUCAPUFdXN0YXIgIABqb3NodWFjYW5ub24dAAcCAA8gAA0PAgCkBAACf3R4dC50eHTGAEIA5QE4NjY0+"
        b"AEECAIDAgAUNQAC7zQwNzAAMDE1NzYyACAwjgBCCwIADwAC7FtwYW50cxMBDwIA"
        b"///////////////////////////////////////////////3UAAAAAAAAAAAABhrfd0="
    )
    input_snapshot = rule_runner.make_snapshot({"test.tar.lz4": archive_content})
    extracted_archive = rule_runner.request(ExtractedArchive, [input_snapshot.digest])
    digest_contents = rule_runner.request(DigestContents, [extracted_archive.digest])
    assert digest_contents == DigestContents([FileContent("tmp/msg/txt.txt", b"pants")])


def test_extract_gz(rule_runner: RuleRunner) -> None:
    # NB: `gz` files are only compressed, and are not archives: they represent a single file.
    name = "test"
    content = b"Hello world!\n"
    io = BytesIO()
    with gzip.GzipFile(fileobj=io, mode="w") as gzf:
        gzf.write(content)
    io.flush()
    input_snapshot = rule_runner.make_snapshot({f"{name}.gz": io.getvalue()})

    rule_runner.set_options(args=[], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    extracted_archive = rule_runner.request(ExtractedArchive, [input_snapshot.digest])
    digest_contents = rule_runner.request(DigestContents, [extracted_archive.digest])
    assert digest_contents == DigestContents([FileContent(name, content)])


def test_extract_non_archive(rule_runner: RuleRunner) -> None:
    input_snapshot = rule_runner.make_snapshot({"test.sh": b"# A shell script"})
    extracted_archive = rule_runner.request(ExtractedArchive, [input_snapshot.digest])
    digest_contents = rule_runner.request(DigestContents, [extracted_archive.digest])
    assert DigestContents([FileContent("test.sh", b"# A shell script")]) == digest_contents


def test_create_zip_archive(rule_runner: RuleRunner) -> None:
    output_filename = "demo/a.zip"
    input_snapshot = rule_runner.make_snapshot(FILES)
    created_digest = rule_runner.request(
        Digest,
        [CreateArchive(input_snapshot, output_filename=output_filename, format=ArchiveFormat.ZIP)],
    )

    digest_contents = rule_runner.request(DigestContents, [created_digest])
    assert len(digest_contents) == 1
    io = BytesIO()
    io.write(digest_contents[0].content)
    with zipfile.ZipFile(io) as zf:
        assert set(zf.namelist()) == set(FILES.keys())

    # We also use Pants to extract the created archive, which checks for idempotency.
    extracted_archive = rule_runner.request(ExtractedArchive, [created_digest])
    digest_contents = rule_runner.request(DigestContents, [extracted_archive.digest])
    assert digest_contents == EXPECTED_DIGEST_CONTENTS


@pytest.mark.parametrize(
    "format", [ArchiveFormat.TAR, ArchiveFormat.TGZ, ArchiveFormat.TXZ, ArchiveFormat.TBZ2]
)
def test_create_tar_archive(rule_runner: RuleRunner, format: ArchiveFormat) -> None:
    output_filename = f"demo/a.{format.value}"
    input_snapshot = rule_runner.make_snapshot(FILES)
    created_digest = rule_runner.request(
        Digest,
        [CreateArchive(input_snapshot, output_filename=output_filename, format=format)],
    )

    digest_contents = rule_runner.request(DigestContents, [created_digest])
    assert len(digest_contents) == 1
    io = BytesIO()
    io.write(digest_contents[0].content)
    io.seek(0)
    compression = "" if format == ArchiveFormat.TAR else f"{format.value[4:]}"  # Strip `tar.`.
    with tarfile.open(fileobj=io, mode=f"r:{compression}") as tf:
        assert set(tf.getnames()) == set(FILES.keys())

    # We also use Pants to extract the created archive, which checks for idempotency.
    extracted_archive = rule_runner.request(ExtractedArchive, [created_digest])
    digest_contents = rule_runner.request(DigestContents, [extracted_archive.digest])
    assert digest_contents == EXPECTED_DIGEST_CONTENTS
