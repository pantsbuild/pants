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
from pants.engine.target import InvalidFieldException, InvalidFieldTypeException
from pants.python.python_requirement import PythonRequirement
from pants.testutil.option_util import create_subsystem


def test_timeout_validation() -> None:
    with pytest.raises(InvalidFieldException):
        PythonTestsTimeout(-100, address=Address.parse(":tests"))
    with pytest.raises(InvalidFieldException):
        PythonTestsTimeout(0, address=Address.parse(":tests"))
    assert PythonTestsTimeout(5, address=Address.parse(":tests")).value == 5


def test_timeout_calculation() -> None:
    def assert_timeout_calculated(
        *,
        field_value: Optional[int],
        expected: Optional[int],
        global_default: Optional[int] = None,
        global_max: Optional[int] = None,
        timeouts_enabled: bool = True,
    ) -> None:
        field = PythonTestsTimeout(field_value, address=Address.parse(":tests"))
        pytest = create_subsystem(
            PyTest,
            timeouts=timeouts_enabled,
            timeout_default=global_default,
            timeout_maximum=global_max,
        )
        assert field.calculate_from_global_options(pytest) == expected

    assert_timeout_calculated(field_value=10, expected=10)
    assert_timeout_calculated(field_value=20, global_max=10, expected=10)
    assert_timeout_calculated(field_value=None, global_default=20, expected=20)
    assert_timeout_calculated(field_value=None, expected=None)
    assert_timeout_calculated(field_value=None, global_default=20, global_max=10, expected=10)
    assert_timeout_calculated(field_value=10, timeouts_enabled=False, expected=None)


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
    raw_value = (
        "argparse==1.2.1",
        "configparser ; python_version<'3'",
        "pip@ git+https://github.com/pypa/pip.git",
    )
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
        "Invalid requirement 'not valid! === 3.1' in the 'requirements' field for the "
        "target demo:"
    ) in str(exc.value)

    # Give a nice error message if it looks like they're trying to use pip VCS-style requirements.
    with pytest.raises(InvalidFieldException) as exc:
        PythonRequirementsField(
            ["git+https://github.com/pypa/pip.git#egg=pip"], address=Address("demo")
        )
    assert "It looks like you're trying to use a pip VCS-style requirement?" in str(exc.value)

    # Check that we still support the deprecated `pants_requirement` object.
    assert (
        PythonRequirementsField(
            [PythonRequirement(v) for v in raw_value], address=Address("demo")
        ).value
        == parsed_value
    )
