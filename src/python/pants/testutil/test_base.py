# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractTestGenerator(ABC):
    """A mixin that facilitates test generation at runtime."""

    @classmethod
    @abstractmethod
    def generate_tests(cls):
        """Generate tests for a given class.

        This should be called against the composing class in its defining module, e.g.

          class ThingTest(TestGenerator):
            ...

          ThingTest.generate_tests()
        """

    @classmethod
    def add_test(cls, method_name, method):
        """A classmethod that adds dynamic test methods to a given class.

        :param string method_name: The name of the test method (e.g. `test_thing_x`).
        :param callable method: A callable representing the method. This should take a 'self' argument
                                as its first parameter for instance method binding.
        """
        assert not hasattr(
            cls, method_name
        ), f"a test with name `{method_name}` already exists on `{cls.__name__}`!"
        assert method_name.startswith("test_"), f"{method_name} is not a valid test name!"
        setattr(cls, method_name, method)
