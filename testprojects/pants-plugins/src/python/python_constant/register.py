# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from python_constant.target_types import PythonConstantTarget, PythonConstantTargetGenerator
from python_constant.target_types import rules as target_types_rules


def target_types():
    return [PythonConstantTarget, PythonConstantTargetGenerator]


def rules():
    return [
        *target_types_rules(),
    ]
