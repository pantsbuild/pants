# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.rules.targets import (
    PythonBinarySources,
    PythonLibrarySources,
    PythonSources,
    PythonTestsSources,
    Timeout,
)
from pants.build_graph.address import Address
from pants.engine.rules import RootRule
from pants.engine.scheduler import ExecutionError
from pants.engine.target import HydratedSources, HydrateSourcesRequest, InvalidFieldException
from pants.engine.target import rules as target_rules
from pants.testutil.test_base import TestBase


def test_timeout_validation() -> None:
    with pytest.raises(InvalidFieldException):
        Timeout(-100, address=Address.parse(":tests"))
    with pytest.raises(InvalidFieldException):
        Timeout(0, address=Address.parse(":tests"))
    assert Timeout(5, address=Address.parse(":tests")).value == 5


class TestPythonSources(TestBase):
    PYTHON_SRC_FILES = ("f1.py", "f2.py")
    PYTHON_TEST_FILES = ("conftest.py", "test_f1.py", "f1_test.py")

    @classmethod
    def rules(cls):
        return [*target_rules(), RootRule(HydrateSourcesRequest)]

    def test_python_sources_validation(self) -> None:
        bad_files = ("f.js", "f.hs", "f.txt")
        files = ("f.py", *bad_files)
        self.create_files(path="", files=files)
        sources = PythonSources(files, address=Address.parse(":lib"))
        assert sources.sanitized_raw_value == tuple(sorted(files))
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(HydratedSources, sources.request)
        assert str(sorted(bad_files)) in str(exc.value)
        assert "//:lib" in str(exc.value)

        # Also check that we support valid sources
        valid_sources = PythonSources(["f.py"], address=Address.parse(":lib"))
        assert valid_sources.sanitized_raw_value == ("f.py",)
        assert self.request_single_product(
            HydratedSources, valid_sources.request
        ).snapshot.files == ("f.py",)

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

    def test_python_library_sources_default_globs(self) -> None:
        self.create_files(path="", files=[*self.PYTHON_SRC_FILES, *self.PYTHON_TEST_FILES])
        sources = PythonLibrarySources(None, address=Address.parse(":lib"))
        result = self.request_single_product(HydratedSources, sources.request)
        assert result.snapshot.files == self.PYTHON_SRC_FILES

    def test_python_tests_sources_default_globs(self) -> None:
        self.create_files(path="", files=[*self.PYTHON_SRC_FILES, *self.PYTHON_TEST_FILES])
        sources = PythonTestsSources(None, address=Address.parse(":tests"))
        result = self.request_single_product(HydratedSources, sources.request)
        assert set(result.snapshot.files) == set(self.PYTHON_TEST_FILES)
