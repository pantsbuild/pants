# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import Match, Optional, Tuple, cast

from pants.backend.python.target_types import PexCompletePlatformsField, PythonResolveField
from pants.backend.python.util_rules.faas import (
    PythonFaaSCompletePlatforms,
    PythonFaaSDependencies,
    PythonFaaSHandlerField,
    PythonFaaSRuntimeField,
)
from pants.backend.python.util_rules.faas import rules as faas_rules
from pants.core.goals.package import OutputPathField
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    InvalidFieldException,
    InvalidTargetException,
    Target,
)
from pants.util.docutil import doc_url
from pants.util.strutil import help_text, softwrap


class PythonAwsLambdaHandlerField(PythonFaaSHandlerField):
    # This doesn't matter (just needs to be fixed), but is the default name used by the AWS
    # console when creating a Python lambda, so is as good as any
    # https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html
    reexported_handler_module = "lambda_function"

    help = help_text(
        f"""
        Entry point to the AWS Lambda handler.

        {PythonFaaSHandlerField.help}

        This is re-exported at `{reexported_handler_module}.handler` in the resulting package to be
        used as the configured handler of the Lambda in AWS. It can also be accessed under its
        source-root-relative module path, for example: `path.to.module.handler_func`.
        """
    )


@dataclass(frozen=True)
class ResolvedPythonAwsHandler:
    val: str
    file_name_used: bool


@dataclass(frozen=True)
class ResolvePythonAwsHandlerRequest:
    field: PythonAwsLambdaHandlerField


class PythonAwsLambdaIncludeRequirements(BoolField):
    alias = "include_requirements"
    default = True
    help = help_text(
        """
        Whether to resolve requirements and include them in the Pex. This is most useful with Lambda
        Layers to make code uploads smaller when deps are in layers.
        https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
        """
    )


class PythonAwsLambdaRuntime(PythonFaaSRuntimeField):
    PYTHON_RUNTIME_REGEX = r"python(?P<major>\d)\.(?P<minor>\d+)"

    help = help_text(
        """
        The identifier of the AWS Lambda runtime to target (pythonX.Y).
        See https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html.

        In general you'll want to define either a `runtime` or one `complete_platforms` but not
        both. Specifying a `runtime` is simpler, but less accurate. If you have issues either
        packaging the AWS Lambda PEX or running it as a deployed AWS Lambda function, you should try
        using `complete_platforms` instead.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return None
        if not re.match(cls.PYTHON_RUNTIME_REGEX, value):
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The `{cls.alias}` field in target at {address} must be of the form pythonX.Y,
                    but was {value}.
                    """
                )
            )
        return value

    def to_interpreter_version(self) -> Optional[Tuple[int, int]]:
        """Returns the Python version implied by the runtime, as (major, minor)."""
        if self.value is None:
            return None
        mo = cast(Match, re.match(self.PYTHON_RUNTIME_REGEX, self.value))
        return int(mo.group("major")), int(mo.group("minor"))


class PythonAWSLambda(Target):
    alias = "python_awslambda"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        PythonFaaSDependencies,
        PythonAwsLambdaHandlerField,
        PythonAwsLambdaIncludeRequirements,
        PythonAwsLambdaRuntime,
        PythonFaaSCompletePlatforms,
        PythonResolveField,
        EnvironmentField,
    )
    help = help_text(
        f"""
        A self-contained Python function suitable for uploading to AWS Lambda.

        See {doc_url('awslambda-python')}.
        """
    )

    def validate(self) -> None:
        if self[PythonAwsLambdaRuntime].value is None and not self[PexCompletePlatformsField].value:
            raise InvalidTargetException(
                softwrap(
                    f"""
                    The `{self.alias}` target {self.address} must specify either a
                    `{self[PythonAwsLambdaRuntime].alias}` or
                    `{self[PexCompletePlatformsField].alias}` or both.
                    """
                )
            )


def rules():
    return (
        *collect_rules(),
        *faas_rules(),
    )
