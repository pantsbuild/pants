# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Create AWS Lambdas from Python code.

See https://pants.readme.io/docs/awslambda-python.
"""

from pants.backend.awslambda.common import awslambda_common_rules
from pants.backend.awslambda.python import awslambda_python_rules
from pants.backend.awslambda.python.target_types import PythonAWSLambda


def rules():
    return [*awslambda_common_rules.rules(), *awslambda_python_rules.rules()]


def target_types():
    return [PythonAWSLambda]
