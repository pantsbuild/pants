# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Match, Optional, Tuple, cast

from pants.backend.awslambda.python.aws_architecture import (
    AWSLambdaArchitecture,
    AWSLambdaArchitectureField,
)
from pants.backend.python.target_types import PexCompletePlatformsField, PythonResolveField
from pants.backend.python.util_rules.faas import (
    PythonFaaSCompletePlatforms,
    PythonFaaSDependencies,
    PythonFaaSHandlerField,
    PythonFaaSKnownRuntime,
    PythonFaaSLayoutField,
    PythonFaaSPex3VenvCreateExtraArgsField,
    PythonFaaSPexBuildExtraArgs,
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
    Field,
    InvalidFieldException,
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
        Whether to resolve requirements and include them in the AWS Lambda artifact. This is most useful with Lambda
        Layers to make code uploads smaller when third-party requirements are in layers.
        https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
        """
    )


class PythonAwsLambdaIncludeSources(BoolField):
    alias = "include_sources"
    default = True
    help = help_text(
        """
        Whether to resolve first party sources and include them in the AWS Lambda artifact. This is
        most useful to allow creating a Lambda Layer with only third-party requirements.
        https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
        """
    )


class PythonAwsLambdaRuntime(PythonFaaSRuntimeField):
    PYTHON_RUNTIME_REGEX = r"python(?P<major>\d)\.(?P<minor>\d+)"

    help = help_text(
        """
        The identifier of the AWS Lambda runtime to target (pythonX.Y).
        See https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html.

        N.B.: only one of this and `complete_platforms` can be set. If `runtime` is set, a default complete
        platform is chosen, if one is known for that runtime. If you have issues either
        packaging the AWS Lambda PEX or running it as a deployed AWS Lambda function, you should try
        using an explicit `complete_platforms` instead.
        """
    )

    # https://gallery.ecr.aws/lambda/python
    known_runtimes_docker_repo = "public.ecr.aws/lambda/python"
    known_runtimes = (
        PythonFaaSKnownRuntime(3, 6, "3.6", AWSLambdaArchitecture.X86_64),
        PythonFaaSKnownRuntime(3, 7, "3.7", AWSLambdaArchitecture.X86_64),
        PythonFaaSKnownRuntime(3, 8, "3.8-x86_64", AWSLambdaArchitecture.X86_64),
        PythonFaaSKnownRuntime(3, 8, "3.8-arm64", AWSLambdaArchitecture.ARM64),
        PythonFaaSKnownRuntime(3, 9, "3.9-x86_64", AWSLambdaArchitecture.X86_64),
        PythonFaaSKnownRuntime(3, 9, "3.9-arm64", AWSLambdaArchitecture.ARM64),
        PythonFaaSKnownRuntime(3, 10, "3.10-x86_64", AWSLambdaArchitecture.X86_64),
        PythonFaaSKnownRuntime(3, 10, "3.10-arm64", AWSLambdaArchitecture.ARM64),
        PythonFaaSKnownRuntime(3, 11, "3.11-x86_64", AWSLambdaArchitecture.X86_64),
        PythonFaaSKnownRuntime(3, 11, "3.11-arm64", AWSLambdaArchitecture.ARM64),
        PythonFaaSKnownRuntime(3, 12, "3.12-x86_64", AWSLambdaArchitecture.X86_64),
        PythonFaaSKnownRuntime(3, 12, "3.12-arm64", AWSLambdaArchitecture.ARM64),
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

    @classmethod
    def from_interpreter_version(cls, py_major: int, py_minor: int) -> str:
        return f"python{py_major}.{py_minor}"


class PythonAwsLambdaLayerDependenciesField(PythonFaaSDependencies):
    required = True


class _AWSLambdaBaseTarget(Target):
    core_fields: ClassVar[tuple[type[Field], ...]] = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        PythonAwsLambdaIncludeRequirements,
        PythonAwsLambdaRuntime,
        PythonFaaSCompletePlatforms,
        PythonFaaSPex3VenvCreateExtraArgsField,
        PythonFaaSPexBuildExtraArgs,
        PythonFaaSLayoutField,
        PythonResolveField,
        EnvironmentField,
    )

    def validate(self) -> None:
        has_runtime = self[PythonAwsLambdaRuntime].value is not None
        has_complete_platforms = self[PexCompletePlatformsField].value is not None

        runtime_alias = self[PythonAwsLambdaRuntime].alias
        complete_platforms_alias = self[PexCompletePlatformsField].alias

        if has_runtime and has_complete_platforms:
            raise ValueError(
                softwrap(
                    f"""
                    The `{complete_platforms_alias}` takes precedence over the `{runtime_alias}` field, if
                    it is set. Remove the `{runtime_alias}` field to only use the `{complete_platforms_alias}`
                    value, or remove the `{complete_platforms_alias}` field to use the default platform
                    implied by `{runtime_alias}`.
                    """
                )
            )


class PythonAWSLambda(_AWSLambdaBaseTarget):
    alias = "python_aws_lambda_function"

    core_fields = (
        *_AWSLambdaBaseTarget.core_fields,
        PythonFaaSDependencies,
        PythonAwsLambdaHandlerField,
        AWSLambdaArchitectureField,
    )
    help = help_text(
        f"""
        A self-contained Python function suitable for uploading to AWS Lambda.

        See {doc_url('docs/python/integrations/aws-lambda')}.
        """
    )


class PythonAWSLambdaLayer(_AWSLambdaBaseTarget):
    alias = "python_aws_lambda_layer"
    core_fields = (
        *_AWSLambdaBaseTarget.core_fields,
        PythonAwsLambdaIncludeSources,
        PythonAwsLambdaLayerDependenciesField,
        AWSLambdaArchitectureField,
    )
    help = help_text(
        f"""
        A Python layer suitable for uploading to AWS Lambda.

        See {doc_url('docs/python/integrations/aws-lambda')}.
        """
    )


def rules():
    return (
        *collect_rules(),
        *faas_rules(),
    )
