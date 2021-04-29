# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
from dataclasses import dataclass
from typing import Match, Optional, Tuple, cast

from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.dependency_inference.rules import PythonInferSubsystem, import_rules
from pants.backend.python.target_types import InterpreterConstraintsField
from pants.core.goals.package import OutputPathField
from pants.engine.addresses import Address
from pants.engine.fs import GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    InvalidFieldException,
    SecondaryOwnerMixin,
    StringField,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.source.filespec import Filespec
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import bracketed_docs_url


class PythonAwsLambdaHandlerField(StringField, AsyncFieldMixin, SecondaryOwnerMixin):
    alias = "handler"
    required = True
    value: str
    help = (
        "Entry point to the AWS Lambda handler.\n\nYou can specify a full module like "
        "'path.to.module:handler_func' or use a shorthand to specify a file name, using the same "
        "syntax as the `sources` field, e.g. 'lambda.py:handler_func'.\n\nYou must use the file "
        "name shorthand for file arguments to work with this target."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> str:
        value = cast(str, super().compute_value(raw_value, address))
        if ":" not in value:
            raise InvalidFieldException(
                f"The `{cls.alias}` field in target at {address} must end in the "
                f"format `:my_handler_func`, but was {value}."
            )
        return value

    @property
    def filespec(self) -> Filespec:
        path, _, func = self.value.partition(":")
        if not path.endswith(".py"):
            return {"includes": []}
        full_glob = os.path.join(self.address.spec_path, path)
        return {"includes": [full_glob]}


@dataclass(frozen=True)
class ResolvedPythonAwsHandler:
    val: str


@dataclass(frozen=True)
class ResolvePythonAwsHandlerRequest:
    field: PythonAwsLambdaHandlerField


@rule(desc="Determining the handler for a `python_awslambda` target")
async def resolve_python_aws_handler(
    request: ResolvePythonAwsHandlerRequest,
) -> ResolvedPythonAwsHandler:
    handler_val = request.field.value
    field_alias = request.field.alias
    address = request.field.address
    path, _, func = handler_val.partition(":")

    # If it's already a module, simply use that. Otherwise, convert the file name into a module
    # path.
    if not path.endswith(".py"):
        return ResolvedPythonAwsHandler(handler_val)

    # Use the engine to validate that the file exists and that it resolves to only one file.
    full_glob = os.path.join(address.spec_path, path)
    handler_paths = await Get(
        Paths,
        PathGlobs(
            [full_glob],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{address}'s `{field_alias}` field",
        ),
    )
    # We will have already raised if the glob did not match, i.e. if there were no files. But
    # we need to check if they used a file glob (`*` or `**`) that resolved to >1 file.
    if len(handler_paths.files) != 1:
        raise InvalidFieldException(
            f"Multiple files matched for the `{field_alias}` {repr(handler_val)} for the target "
            f"{address}, but only one file expected. Are you using a glob, rather than a file "
            f"name?\n\nAll matching files: {list(handler_paths.files)}."
        )
    handler_path = handler_paths.files[0]
    source_root = await Get(
        SourceRoot,
        SourceRootRequest,
        SourceRootRequest.for_file(handler_path),
    )
    stripped_source_path = os.path.relpath(handler_path, source_root.path)
    module_base, _ = os.path.splitext(stripped_source_path)
    normalized_path = module_base.replace(os.path.sep, ".")
    return ResolvedPythonAwsHandler(f"{normalized_path}:{func}")


class PythonAwsLambdaDependencies(Dependencies):
    supports_transitive_excludes = True


class InjectPythonLambdaHandlerDependency(InjectDependenciesRequest):
    inject_for = PythonAwsLambdaDependencies


@rule(desc="Inferring dependency from the python_awslambda `handler` field")
async def inject_lambda_handler_dependency(
    request: InjectPythonLambdaHandlerDependency, python_infer_subsystem: PythonInferSubsystem
) -> InjectedDependencies:
    if not python_infer_subsystem.entry_points:
        return InjectedDependencies()
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    explicitly_provided_deps, handler = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(original_tgt.target[Dependencies])),
        Get(
            ResolvedPythonAwsHandler,
            ResolvePythonAwsHandlerRequest(original_tgt.target[PythonAwsLambdaHandlerField]),
        ),
    )
    module, _, _func = handler.val.partition(":")
    owners = await Get(PythonModuleOwners, PythonModule(module))
    address = original_tgt.target.address
    explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
        owners.ambiguous,
        address,
        import_reference="module",
        context=(
            f"The python_awslambda target {address} has the field "
            f"`handler={repr(original_tgt.target[PythonAwsLambdaHandlerField].value)}`, which maps "
            f"to the Python module `{module}`"
        ),
    )
    maybe_disambiguated = explicitly_provided_deps.disambiguated_via_ignores(owners.ambiguous)
    unambiguous_owners = owners.unambiguous or (
        (maybe_disambiguated,) if maybe_disambiguated else ()
    )
    return InjectedDependencies(unambiguous_owners)


class PythonAwsLambdaRuntime(StringField):
    PYTHON_RUNTIME_REGEX = r"python(?P<major>\d)\.(?P<minor>\d+)"

    alias = "runtime"
    required = True
    value: str
    help = (
        "The identifier of the AWS Lambda runtime to target (pythonX.Y). See "
        "https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> str:
        value = cast(str, super().compute_value(raw_value, address))
        if not re.match(cls.PYTHON_RUNTIME_REGEX, value):
            raise InvalidFieldException(
                f"The `{cls.alias}` field in target at {address} must be of the form pythonX.Y, "
                f"but was {value}."
            )
        return value

    def to_interpreter_version(self) -> Tuple[int, int]:
        """Returns the Python version implied by the runtime, as (major, minor)."""
        mo = cast(Match, re.match(self.PYTHON_RUNTIME_REGEX, self.value))
        return int(mo.group("major")), int(mo.group("minor"))


class PythonAWSLambda(Target):
    alias = "python_awslambda"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        InterpreterConstraintsField,
        PythonAwsLambdaDependencies,
        PythonAwsLambdaHandlerField,
        PythonAwsLambdaRuntime,
    )
    help = (
        "A self-contained Python function suitable for uploading to AWS Lambda.\n\nSee "
        f"{bracketed_docs_url('awslambda-python')}."
    )


def rules():
    return (
        *collect_rules(),
        *import_rules(),
        UnionRule(InjectDependenciesRequest, InjectPythonLambdaHandlerDependency),
    )
