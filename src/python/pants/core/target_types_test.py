# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict

from pants.core.target_types import (
    ApplyPrefixMappingRequest,
    PrefixMappedSnapshot,
    SourcesPrefixMapping,
)
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_path_prefix_mapping() -> None:
    rule_runner = RuleRunner(rules=[QueryRule(PrefixMappedSnapshot, (ApplyPrefixMappingRequest,))])

    def assert_prefix_mapping(
        *,
        original: str,
        mapping: Dict[str, str],
        expected: str,
    ) -> None:
        original_snapshot = rule_runner.make_snapshot_of_empty_files([original])
        field = SourcesPrefixMapping(mapping, address=Address("foo"))
        result = rule_runner.request(
            PrefixMappedSnapshot, [ApplyPrefixMappingRequest(original_snapshot, field)]
        )
        assert result.snapshot.files == (expected,)

    assert_prefix_mapping(original="old_prefix/f.ext", mapping={}, expected="old_prefix/f.ext")
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        mapping={"old_prefix": "old_prefix"},
        expected="old_prefix/f.ext",
    )

    assert_prefix_mapping(original="old_prefix/f.ext", mapping={"old_prefix": ""}, expected="f.ext")
    assert_prefix_mapping(
        original="old_prefix/subdir/f.ext", mapping={"old_prefix": ""}, expected="subdir/f.ext"
    )

    assert_prefix_mapping(original="f.ext", mapping={"": "new_prefix"}, expected="new_prefix/f.ext")
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        mapping={"": "new_prefix"},
        expected="new_prefix/old_prefix/f.ext",
    )

    assert_prefix_mapping(
        original="old_prefix/f.ext",
        mapping={"old_prefix": "new_prefix"},
        expected="new_prefix/f.ext",
    )
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        mapping={"old_prefix": "new_prefix/subdir"},
        expected="new_prefix/subdir/f.ext",
    )

    assert_prefix_mapping(
        original="common_prefix/foo/f.ext",
        mapping={"common_prefix/foo": "common_prefix/bar"},
        expected="common_prefix/bar/f.ext",
    )
    assert_prefix_mapping(
        original="common_prefix/subdir/f.ext",
        mapping={"common_prefix/subdir": "common_prefix"},
        expected="common_prefix/f.ext",
    )
