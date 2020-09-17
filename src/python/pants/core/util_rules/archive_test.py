# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import tarfile
import zipfile
from io import BytesIO

import pytest

from pants.core.util_rules.archive import ExtractedDigest, MaybeExtractable
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import DigestContents, FileContent
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[*archive_rules(), QueryRule(ExtractedDigest, (MaybeExtractable,))])


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
    extracted_digest = rule_runner.request(
        ExtractedDigest, [MaybeExtractable(input_snapshot.digest)]
    )

    digest_contents = rule_runner.request(DigestContents, [extracted_digest.digest])
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
    extracted_digest = rule_runner.request(
        ExtractedDigest, [MaybeExtractable(input_snapshot.digest)]
    )

    digest_contents = rule_runner.request(DigestContents, [extracted_digest.digest])
    assert digest_contents == EXPECTED_DIGEST_CONTENTS


def test_non_archive(rule_runner: RuleRunner) -> None:
    input_snapshot = rule_runner.make_snapshot({"test.sh": b"# A shell script"})
    extracted_digest = rule_runner.request(
        ExtractedDigest, [MaybeExtractable(input_snapshot.digest)]
    )

    digest_contents = rule_runner.request(DigestContents, [extracted_digest.digest])
    assert DigestContents([FileContent("test.sh", b"# A shell script")]) == digest_contents
