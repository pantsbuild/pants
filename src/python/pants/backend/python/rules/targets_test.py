# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.rules.targets import (
    PythonBinary,
    PythonBinarySources,
    PythonLibrary,
    PythonLibrarySources,
    PythonSources,
    PythonTests,
    PythonTestsSources,
    Timeout,
)
from pants.build_graph.address import Address
from pants.engine.rules import RootRule
from pants.engine.target import Sources, SourcesResult
from pants.testutil.test_base import TestBase


def test_timeout_validation() -> None:
    with pytest.raises(ValueError):
        Timeout(-100, address=Address.parse(":tests"))
    with pytest.raises(ValueError):
        Timeout(0, address=Address.parse(":tests"))
    assert Timeout(5, address=Address.parse(":tests")).value == 5


class TestPythonSources(TestBase):
    @classmethod
    def rules(cls):
        return [
            RootRule(PythonSources),
            RootRule(PythonBinarySources),
            RootRule(PythonLibrarySources),
            RootRule(PythonTestsSources),
        ]

    def test_python_sources_validation(self) -> None:
        pass

    def test_python_library_sources_default_globs(self) -> None:
        self.create_files(
            path="", files=["f1.py", "f2.py", "conftest.py", "test_f1.py", "f1_test.py"]
        )
        tgt = PythonLibrary({}, address=Address.parse(":lib"))
        result = self.request_single_product(SourcesResult, tgt.get(Sources))
        assert result.snapshot.files == ("f1.py", "f2.py")

    def test_python_tests_sources(self) -> None:
        pass

    def test_python_binary_sources(self) -> None:
        pass
