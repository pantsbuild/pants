# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from typing import Match, Optional, Tuple, cast

from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonInterpreterCompatibility,
    PythonSources,
)
from pants.core.goals.package import OutputPathField
from pants.engine.addresses import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    InvalidFieldException,
    StringField,
    Target,
)


class PythonAwsLambdaSources(PythonSources):
    expected_num_files = range(0, 2)


class PythonAwsLambdaDependencies(Dependencies):
    supports_transitive_excludes = True


class PythonAwsLambdaHandler(StringField):
    """AWS Lambda handler entrypoint (module.dotted.name:handler_func)."""

    alias = "handler"
    required = True
    value: str


class PythonAwsLambdaRuntime(StringField):
    """The identifier of the AWS Lambda runtime to target (pythonX.Y).

    See https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html.
    """

    PYTHON_RUNTIME_REGEX = r"python(?P<major>\d)\.(?P<minor>\d+)"

    alias = "runtime"
    required = True
    value: str

    @classmethod
    def compute_value(cls, raw_value: Optional[str], *, address: Address) -> str:
        value = cast(str, super().compute_value(raw_value, address=address))
        if not re.match(cls.PYTHON_RUNTIME_REGEX, value):
            raise InvalidFieldException(
                f"runtime field in python_awslambda target at {address.spec} must "
                f"be of the form pythonX.Y, but was {value}"
            )
        return value

    def to_interpreter_version(self) -> Tuple[int, int]:
        """Returns the Python version implied by the runtime, as (major, minor)."""
        mo = cast(Match, re.match(self.PYTHON_RUNTIME_REGEX, self.value))
        return int(mo.group("major")), int(mo.group("minor"))


class PythonAWSLambda(Target):
    """A self-contained Python function suitable for uploading to AWS Lambda.

    See https://www.pantsbuild.org/docs/awslambda-python.
    """

    alias = "python_awslambda"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonAwsLambdaSources,
        PythonInterpreterCompatibility,
        InterpreterConstraintsField,
        OutputPathField,
        PythonAwsLambdaDependencies,
        PythonAwsLambdaHandler,
        PythonAwsLambdaRuntime,
    )
