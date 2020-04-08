# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.targets import (
    COMMON_PYTHON_FIELDS,
    PythonBinarySources,
    PythonEntryPoint,
)
from pants.engine.target import Target


# NB: By subclassing PythonEntryPoint, this field will work with goals like `./pants binary`.
class PythonAwsLambdaHandler(PythonEntryPoint):
    """Lambda handler entrypoint (module.dotted.name:handler_func)."""

    alias = "handler"
    required = True
    value: str


class PythonAWSLambda(Target):
    """A self-contained Python function suitable for uploading to AWS Lambda."""

    alias = "python_awslambda"
    core_fields = (*COMMON_PYTHON_FIELDS, PythonBinarySources, PythonAwsLambdaHandler)
