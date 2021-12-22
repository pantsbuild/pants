# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from contextlib import contextmanager


def assert_logged(caplog, expect_logged: list[tuple[int, str]] | None = None) -> None:
    if not expect_logged:
        assert not caplog.records
        return

    assert len(caplog.records) == len(
        expect_logged
    ), f"Expected {len(expect_logged)} records, but got {len(caplog.records)}."
    for idx, (lvl, msg) in enumerate(expect_logged):
        log_record = caplog.records[idx]
        assert (
            msg in log_record.message
        ), f"The text {msg!r} was not found in {log_record.message!r}."
        assert (
            lvl == log_record.levelno
        ), f"Expected level {lvl}, but got level {log_record.levelno}."


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
