# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.help.maybe_color import MaybeColor


def test_produce_fmt_matches() -> None:
    dummy = MaybeColor(color=False)
    diff_ex = ["match1", "match2", "match3"]
    one_match = dummy._format_did_you_mean_matches(diff_ex[:1])
    assert one_match == "match1"
    two_match = dummy._format_did_you_mean_matches(diff_ex[:2])
    assert two_match == "match1 or match2"
    three_match = dummy._format_did_you_mean_matches(diff_ex[:3])
    assert three_match == "match1, match2, or match3"
