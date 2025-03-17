import doctest

import external_tool_upgrade


def test_docs() -> None:
    failure_count, test_count = doctest.testmod(external_tool_upgrade)
    assert test_count > 0
    assert failure_count == 0
