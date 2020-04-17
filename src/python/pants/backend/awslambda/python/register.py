# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Create AWS Lambdas from Python code."""

from pants.backend.awslambda.common import awslambda_common_rules
from pants.backend.awslambda.python import awslambda_python_rules
from pants.backend.awslambda.python.targets import PythonAWSLambda
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target


def rules():
    return [*awslambda_common_rules.rules(), *awslambda_python_rules.rules()]


def targets2():
    return [PythonAWSLambda]


# Dummy v1 target to ensure that v1 tasks can still parse v2 BUILD files.
class LegacyPythonAWSLambda(Target):
    def __init__(self, handler=None, **kwargs):
        super().__init__(**kwargs)


def build_file_aliases2():
    return BuildFileAliases(targets={"python_awslambda": LegacyPythonAWSLambda})
