# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import Match, Optional, Tuple, cast

from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.dependency_inference.rules import import_rules
from pants.backend.python.target_types import InterpreterConstraintsField, PythonSources
from pants.core.goals.package import OutputPathField
from pants.engine.addresses import Address
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    Dependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    InvalidFieldException,
    StringField,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem


class PythonAwsLambdaDefaults(Subsystem):
    """Default settings for the `python_awslambda` target."""

    options_scope = "python-awslambda-defaults"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--infer-dependencies",
            advanced=True,
            type=bool,
            default=True,
            help="Infer a dependency on the module specified by the `handler` field.",
        )

    @property
    def infer_dependencies(self) -> bool:
        return cast(bool, self.options.infer_dependencies)


class PythonAwsLambdaSources(PythonSources):
    expected_num_files = range(0, 2)


class PythonAwsLambdaHandlerField(StringField, AsyncFieldMixin):
    """AWS Lambda handler entrypoint (module.dotted.name:handler_func)."""

    alias = "handler"
    required = True
    value: str


@dataclass(frozen=True)
class ResolvedPythonAwsHandler:
    val: str


@dataclass(frozen=True)
class ResolvePythonAwsHandlerRequest:
    field: PythonAwsLambdaHandlerField


@rule
async def resolve_python_aws_handler(
    request: ResolvePythonAwsHandlerRequest,
) -> ResolvedPythonAwsHandler:
    return ResolvedPythonAwsHandler(request.field.value)


class PythonAwsLambdaDependencies(Dependencies):
    supports_transitive_excludes = True


class InjectPythonLambdaHandlerDependency(InjectDependenciesRequest):
    inject_for = PythonAwsLambdaDependencies


@rule(desc="Inferring dependency from the python_awslambda `handler` field")
async def inject_lambda_handler_dependency(
    request: InjectPythonLambdaHandlerDependency, awslambda_defaults: PythonAwsLambdaDefaults
) -> InjectedDependencies:
    if not awslambda_defaults.infer_dependencies:
        return InjectedDependencies()
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    handler = await Get(
        ResolvedPythonAwsHandler,
        ResolvePythonAwsHandlerRequest(original_tgt.target[PythonAwsLambdaHandlerField]),
    )
    module, _, _func = handler.val.partition(":")
    owners = await Get(PythonModuleOwners, PythonModule(module))
    # TODO: remove the check for == self once the `sources` field is removed.
    return InjectedDependencies(
        owner for owner in owners if owner != request.dependencies_field.address
    )


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
        InterpreterConstraintsField,
        OutputPathField,
        PythonAwsLambdaDependencies,
        PythonAwsLambdaHandlerField,
        PythonAwsLambdaRuntime,
    )


def rules():
    return (
        *collect_rules(),
        *import_rules(),
        UnionRule(InjectDependenciesRequest, InjectPythonLambdaHandlerDependency),
    )
