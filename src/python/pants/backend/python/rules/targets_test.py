# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional

import pytest

from pants.backend.python.rules.targets import PythonBinarySources, Timeout
from pants.backend.python.subsystems.pytest import PyTest
from pants.build_graph.address import Address
from pants.engine.rules import RootRule
from pants.engine.scheduler import ExecutionError
from pants.engine.target import HydratedSources, HydrateSourcesRequest, InvalidFieldException
from pants.engine.target import rules as target_rules
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.testutil.test_base import TestBase


class TestTimeout(TestBase):
    def test_timeout_validation(self) -> None:
        with pytest.raises(InvalidFieldException):
            Timeout(-100, address=Address.parse(":tests"))
        with pytest.raises(InvalidFieldException):
            Timeout(0, address=Address.parse(":tests"))
        assert Timeout(5, address=Address.parse(":tests")).value == 5

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
        field = Timeout(field_value, address=Address.parse(":tests"))
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


class TestPythonSources(TestBase):
    @classmethod
    def rules(cls):
        return [*target_rules(), RootRule(HydrateSourcesRequest)]

    def test_python_binary_sources_validation(self) -> None:
        self.create_files(path="", files=["f1.py", "f2.py"])
        address = Address.parse(":binary")

        zero_sources = PythonBinarySources(None, address=address)
        assert (
            self.request_single_product(HydratedSources, zero_sources.request).snapshot.files == ()
        )

        one_source = PythonBinarySources(["f1.py"], address=address)
        assert self.request_single_product(HydratedSources, one_source.request).snapshot.files == (
            "f1.py",
        )

        multiple_sources = PythonBinarySources(["f1.py", "f2.py"], address=address)
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(HydratedSources, multiple_sources.request)
        assert "has 2 sources" in str(exc.value)
