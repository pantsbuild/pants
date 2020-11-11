# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from typing import Callable, Optional


def assert_equal_with_printing(
    test_case, expected, actual, uniform_formatter: Optional[Callable[[str], str]] = None
):
    """Asserts equality, but also prints the values so they can be compared on failure.

    Usage:

       class FooTest(unittest.TestCase):
         assert_equal_with_printing = assert_equal_with_printing

         def test_foo(self):
           self.assert_equal_with_printing("a", "b")
    """
    str_actual = str(actual)
    print("Expected:")
    print(expected)
    print("Actual:")
    print(str_actual)

    if uniform_formatter is not None:
        expected = uniform_formatter(expected)
        str_actual = uniform_formatter(str_actual)

    test_case.assertEqual(expected, str_actual)


def remove_locations_from_traceback(trace: str) -> str:
    location_pattern = re.compile(r'"/.*", line \d+')
    address_pattern = re.compile(r"0x[0-9a-f]+")
    new_trace = location_pattern.sub("LOCATION-INFO", trace)
    new_trace = address_pattern.sub("0xEEEEEEEEE", new_trace)
    return new_trace
