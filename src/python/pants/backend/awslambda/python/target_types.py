# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Match, Optional, Tuple, cast

from pants.backend.python.target_types import PexCompletePlatformsField, PythonResolveField
from pants.backend.python.util_rules.faas import (
    FaaSArchitecture,
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
    StringField,
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


PYTHON_RUNTIME_REGEX = r"python(?P<major>\d)\.(?P<minor>\d+)"


class PythonAwsLambdaFunctionRuntimes(Enum):
    PYTHON_36 = "python3.6"
    PYTHON_37 = "python3.7"
    PYTHON_38 = "python3.8"
    PYTHON_39 = "python3.9"
    PYTHON_310 = "python3.10"
    PYTHON_311 = "python3.11"
    PYTHON_312 = "python3.12"

    def to_interpreter_version(self) -> Tuple[int, int]:
        """Returns the Python version implied by the runtime, as (major, minor)."""
        mo = cast(Match, re.match(PYTHON_RUNTIME_REGEX, self.value))
        return int(mo.group("major")), int(mo.group("minor"))


LAMBDA_DOCKER_REPO = "public.ecr.aws/lambda/python"


class PythonAwsLambdaRuntime(PythonFaaSRuntimeField):
    # https://gallery.ecr.aws/lambda/python
    RUNTIME_TAG_MAPPING = {
        (PythonAwsLambdaFunctionRuntimes.PYTHON_36, FaaSArchitecture.X86_64): "3.6",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_37, FaaSArchitecture.X86_64): "3.7",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_38, FaaSArchitecture.X86_64): "3.8-x86_64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_38, FaaSArchitecture.ARM64): "3.8-arm64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_39, FaaSArchitecture.X86_64): "3.9-x86_64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_39, FaaSArchitecture.ARM64): "3.9-arm64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_310, FaaSArchitecture.X86_64): "3.10-x86_64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_310, FaaSArchitecture.ARM64): "3.10-arm64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_311, FaaSArchitecture.X86_64): "3.11-x86_64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_311, FaaSArchitecture.ARM64): "3.11-arm64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_312, FaaSArchitecture.X86_64): "3.12-x86_64",
        (PythonAwsLambdaFunctionRuntimes.PYTHON_312, FaaSArchitecture.ARM64): "3.12-arm64",
    }

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

    valid_choices = PythonAwsLambdaFunctionRuntimes
    known_runtimes = tuple(
        PythonFaaSKnownRuntime(
            runtime.value, *runtime.to_interpreter_version(), LAMBDA_DOCKER_REPO, tag, architecture
        )
        for (runtime, architecture), tag in RUNTIME_TAG_MAPPING.items()
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return None
        if not re.match(PYTHON_RUNTIME_REGEX, value):
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
        mo = cast(Match, re.match(PYTHON_RUNTIME_REGEX, self.value))
        return int(mo.group("major")), int(mo.group("minor"))

    @classmethod
    def from_interpreter_version(cls, py_major: int, py_minor: int) -> str:
        return f"python{py_major}.{py_minor}"


class AWSLambdaArchitectureField(StringField):
    alias = "architecture"
    valid_choices = FaaSArchitecture
    expected_type = str
    default = FaaSArchitecture.X86_64.value
    help = help_text(
        """
        The architecture of the AWS Lambda runtime to target (x86_64 or arm64).
        See https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html.
        """
    )


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
