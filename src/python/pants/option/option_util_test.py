# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from unittest import TestCase

from pants.option.option_util import flatten_shlexed_list


class OptionUtilTest(TestCase):
    def test_flatten_shlexed_list(self) -> None:
        assert flatten_shlexed_list(["arg1", "arg2"]) == ["arg1", "arg2"]
        assert flatten_shlexed_list(["arg1 arg2"]) == ["arg1", "arg2"]
        assert flatten_shlexed_list(["arg1 arg2=foo", "--arg3"]) == ["arg1", "arg2=foo", "--arg3"]
        assert flatten_shlexed_list(["arg1='foo bar'", "arg2='baz'"]) == [
            "arg1=foo bar",
            "arg2=baz",
        ]
