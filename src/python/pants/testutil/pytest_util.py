# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager


@contextmanager
def no_exception():
    """Useful replacement for `pytest.raises()`, when there is no exception to be expected.

    When declaring parametrized tests, the test function can take a exceptions
    expectation as input, and always use a with-block for the code under test.

        @pytest.mark.parametrize('answer, expect_raises', [
            (42, no_exception()),
            (12, pytest.raises(WrongAnswer)),
        ])
        def test_search_for_the_meaning_of_life_universe_and_everything(answer, expect_raises):
            with expect_raises:
                computer.validate_result(answer)
    """
    yield None
