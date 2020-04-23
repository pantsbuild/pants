# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, StringField, Target


class PythonAwsLambdaBinaryField(StringField):
    """Target spec of the `python_binary` that contains the handler."""

    alias = "binary"


class PythonAwsLambdaHandler(StringField):
    """Lambda handler entrypoint (module.dotted.name:handler_func)."""

    alias = "handler"


class PythonAWSLambda(Target):
    """A self-contained Python function suitable for uploading to AWS Lambda."""

    alias = "python_awslambda"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        PythonAwsLambdaBinaryField,
        PythonAwsLambdaHandler,
    )
    v1_only = True
