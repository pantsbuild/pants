# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional

import pytest

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.target_types import PythonBinarySources, PythonTestsTimeout
from pants.engine.addresses import Address
from pants.engine.target import InvalidFieldException
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.testutil.test_base import TestBase


class TestTimeout(TestBase):
    def test_timeout_validation(self) -> None:
        with pytest.raises(InvalidFieldException):
            PythonTestsTimeout(-100, address=Address.parse(":tests"))
        with pytest.raises(InvalidFieldException):
            PythonTestsTimeout(0, address=Address.parse(":tests"))
        assert PythonTestsTimeout(5, address=Address.parse(":tests")).value == 5

    def assert_timeout_calculated(
        self,
        *,
        field_value: Optional[int],
        expected: Optional[int],
        global_default: Optional[int] = None,
        global_max: Optional[int] = None,
        timeouts_enabled: bool = True
    ) -> None:
        pytest = global_subsystem_instance(
            PyTest,
            options={
                PyTest.options_scope: {
                    "timeouts": timeouts_enabled,
                    "timeout_default": global_default,
                    "timeout_maximum": global_max,
                }
            },
        )
        field = PythonTestsTimeout(field_value, address=Address.parse(":tests"))
        assert field.calculate_from_global_options(pytest) == expected

    def test_valid_field_timeout(self) -> None:
        self.assert_timeout_calculated(field_value=10, expected=10)

    def test_field_timeout_greater_than_max(self) -> None:
        self.assert_timeout_calculated(field_value=20, global_max=10, expected=10)

    def test_no_field_timeout_uses_default(self) -> None:
        self.assert_timeout_calculated(field_value=None, global_default=20, expected=20)

    def test_no_field_timeout_and_no_default(self) -> None:
        self.assert_timeout_calculated(field_value=None, expected=None)

    def test_no_field_timeout_and_default_greater_than_max(self) -> None:
        self.assert_timeout_calculated(
            field_value=None, global_default=20, global_max=10, expected=10
        )

    def test_timeouts_disabled(self) -> None:
        self.assert_timeout_calculated(field_value=10, timeouts_enabled=False, expected=None)


def test_translate_source_file_to_entry_point() -> None:
    assert (
        PythonBinarySources.translate_source_file_to_entry_point(["example/app.py"])
        == "example.app"
    )
    # NB: the onus is on the call site to strip the source roots before calling this method.
    assert (
        PythonBinarySources.translate_source_file_to_entry_point(["src/python/app.py"])
        == "src.python.app"
    )
    assert PythonBinarySources.translate_source_file_to_entry_point([]) is None
    assert PythonBinarySources.translate_source_file_to_entry_point(["f1.py", "f2.py"]) is None
