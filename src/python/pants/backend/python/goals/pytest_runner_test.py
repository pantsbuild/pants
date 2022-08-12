# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals.pytest_runner import _count_pytest_tests
from pants.engine.fs import DigestContents, FileContent

EXAMPLE_TEST1 = b"""
def test_foo():
    pass

def test_bar():
    pass
"""

EXAMPLE_TEST2 = b"""
class TestStuff(TestCase):
    def test_baz():
        pass

    def testHelper():
        pass
"""


def test_count_pytest_tests() -> None:
    digest_contents = DigestContents(
        [
            FileContent(path="tests/test_empty.py", content=b""),
            FileContent(path="tests/test_example1.py", content=EXAMPLE_TEST1),
            FileContent(path="tests/test_example2.py", content=EXAMPLE_TEST2),
        ]
    )
    test_count = _count_pytest_tests(digest_contents)
    assert test_count == 3
