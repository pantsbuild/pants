# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Create AWS Lambdas from Python code.

See https://www.pantsbuild.org/docs/awslambda-python.
"""

from pants.backend.awslambda.python import rules as python_rules
from pants.backend.awslambda.python.target_types import PythonAWSLambda


def rules():
    return python_rules.rules()


def target_types():
    return [PythonAWSLambda]
