# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib

import pytest

from pants.engine.fs import EMPTY_FILE_DIGEST, CreateDigest, Digest, FileContent, FileDigest
from pants.jvm.util_rules import ExtractFileDigest
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *util_rules(),
            QueryRule(FileDigest, (ExtractFileDigest,)),
        ],
    )


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_extract_empty_file(rule_runner: RuleRunner) -> None:
    digest = get_digest(rule_runner, {"foo.txt": ""})
    file_digest = rule_runner.request(
        FileDigest,
        [ExtractFileDigest(digest=digest, file_path="foo.txt")],
    )
    assert file_digest == EMPTY_FILE_DIGEST


def test_extract_nonempty_file(rule_runner: RuleRunner) -> None:
    digest = get_digest(rule_runner, {"foo.txt": "bar"})
    file_digest = rule_runner.request(
        FileDigest,
        [ExtractFileDigest(digest=digest, file_path="foo.txt")],
    )
    hasher = hashlib.sha256()
    hasher.update(b"bar")
    assert file_digest == FileDigest(fingerprint=hasher.hexdigest(), serialized_bytes_length=3)


def test_extract_missing_file(rule_runner: RuleRunner) -> None:
    digest = get_digest(rule_runner, {"foo.txt": ""})
    with pytest.raises(Exception, match=r".*?not found in.*?"):
        rule_runner.request(
            FileDigest,
            [ExtractFileDigest(digest=digest, file_path="missing")],
        )


def test_subset_with_multiple_files(rule_runner: RuleRunner) -> None:
    digest = get_digest(rule_runner, {"foo.txt": "", "bar.txt": ""})
    with pytest.raises(Exception, match=r".*?found multiple times.*?"):
        rule_runner.request(
            FileDigest,
            [ExtractFileDigest(digest=digest, file_path="*")],
        )
