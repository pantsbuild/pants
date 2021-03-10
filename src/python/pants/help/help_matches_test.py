# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.help.maybe_color import MaybeColor


def test_produce_fmt_matches() -> None:
    # The code for the produce_formatted_matches is identical for both of the
    # places it's in - HelpPrinter, and FlagErrorPrinter. Therefore, there
    # isn't a need to test it twice.

    dummy = MaybeColor(color=False)
    diff_ex = ["match1", "match2", "match3"]
    one_match = dummy._produce_formatted_matches(diff_ex[:1])
    assert one_match == "match1"
    two_match = dummy._produce_formatted_matches(diff_ex[:2])
    assert two_match == "match1 or match2"
    three_match = dummy._produce_formatted_matches(diff_ex[:3])
    assert three_match == "match1, match2, or match3"
