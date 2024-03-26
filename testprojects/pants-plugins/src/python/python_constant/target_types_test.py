# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest
from python_constant import target_types
from python_constant.target_types import (
    PythonConstant,
    PythonConstantTarget,
    PythonConstantTargetGenerator,
    PythonConstantVisitor,
)

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import module_mapper
from pants.backend.python.target_types import PythonSourcesGeneratorTarget, PythonSourceTarget
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import QueryRule
from pants.engine.target import Dependencies, DependenciesRequest
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner():
    return RuleRunner(
        rules=[
            *target_types.rules(),
            *module_mapper.rules(),
            *stripped_source_files.rules(),
            *target_types_rules.rules(),
            # python_register.rules(),
            QueryRule(Addresses, (DependenciesRequest,)),
        ],
        target_types=[
            PythonSourceTarget,
            PythonSourcesGeneratorTarget,
            # *python_register.target_types(),
            PythonConstantTarget,
            PythonConstantTargetGenerator,
        ],
    )


_CONSTANTS_MODULE = """\
int_constant = 42
array_constant = [
    "pants",
    "is",
    "awesome",
]

dict_constant = {
    "mercury": 2440,
    "venus": 6052,
    "earth": 6371,
}
"""


def test_parse_python_constants():
    content = _CONSTANTS_MODULE
    constants = PythonConstantVisitor.parse_constants(content.encode("utf-8"))
    assert constants == [
        PythonConstant(python_contant="int_constant", lineno=1, end_lineno=1),
        PythonConstant(python_contant="array_constant", lineno=2, end_lineno=6),
        PythonConstant(python_contant="dict_constant", lineno=8, end_lineno=12),
    ]


def test_infer_dependencies(rule_runner: RuleRunner):
    rule_runner.write_files(
        {
            "src/constants.py": _CONSTANTS_MODULE,
            "src/run.py": dedent(
                """\
                from constants import array_constant
                print(array_constant)
                """
            ),
            "src/BUILD": dedent(
                """\
                python_constants(name="const", source="constants.py")
                python_sources(name="src")
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src", target_name="src", relative_file_path="run.py"))
    addresses = rule_runner.request(Addresses, [DependenciesRequest(tgt.get(Dependencies))])
    assert addresses == Addresses(
        [
            Address("src", target_name="const", generated_name="array_constant"),
            #
            # You will probably want to disable this dependency in the real plugin
            # and rely only on python_constant.
            Address("src", relative_file_path="constants.py"),
        ]
    )
