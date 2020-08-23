# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional

import pytest
from pkg_resources import Requirement

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.target_types import (
    PythonBinarySources,
    PythonRequirementsField,
    PythonTestsTimeout,
)
from pants.engine.addresses import Address
from pants.engine.rules import SubsystemRule
from pants.engine.target import InvalidFieldException, InvalidFieldTypeException
from pants.python.python_requirement import PythonRequirement
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class TestTimeout(TestBase):
    @classmethod
    def rules(cls):
        return [*super().rules(), SubsystemRule(PyTest)]

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
        timeouts_enabled: bool = True,
    ) -> None:
        args = ["--backend-packages=pants.backend.python", f"--pytest-timeouts={timeouts_enabled}"]
        if global_default is not None:
            args.append(f"--pytest-timeout-default={global_default}")
        if global_max is not None:
            args.append(f"--pytest-timeout-maximum={global_max}")
        pytest = self.request_product(PyTest, create_options_bootstrapper(args=args))
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


def test_requirements_field() -> None:
    raw_value = ("argparse==1.2.1", "configparser ; python_version<'3'")
    parsed_value = tuple(Requirement.parse(v) for v in raw_value)

    assert PythonRequirementsField(raw_value, address=Address("demo")).value == parsed_value

    # Macros can pass pre-parsed Requirement objects.
    assert PythonRequirementsField(parsed_value, address=Address("demo")).value == parsed_value

    # Reject invalid types.
    with pytest.raises(InvalidFieldTypeException):
        PythonRequirementsField("sneaky_str", address=Address("demo"))
    with pytest.raises(InvalidFieldTypeException):
        PythonRequirementsField([1, 2], address=Address("demo"))

    # Give a nice error message if the requirement can't be parsed.
    with pytest.raises(InvalidFieldException) as exc:
        PythonRequirementsField(["not valid! === 3.1"], address=Address("demo"))
    assert (
        "Invalid requirement string 'not valid! === 3.1' in the 'requirements' field for the "
        "target demo:"
    ) in str(exc.value)

    # Check that we still support the deprecated `pants_requirement` object.
    assert (
        PythonRequirementsField(
            [PythonRequirement(v) for v in raw_value], address=Address("demo")
        ).value
        == parsed_value
    )
