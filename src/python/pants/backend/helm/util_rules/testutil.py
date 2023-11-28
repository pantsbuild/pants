# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.engine.fs import DigestContents, DigestSubset, PathGlobs
from pants.engine.internals.native_engine import Digest
from pants.testutil.rule_runner import RuleRunner


def _read_file_from_digest(rule_runner: RuleRunner, *, digest: Digest, filename: str) -> str:
    config_file_digest = rule_runner.request(Digest, [DigestSubset(digest, PathGlobs([filename]))])
    config_file_contents = rule_runner.request(DigestContents, [config_file_digest])
    return config_file_contents[0].content.decode("utf-8")
