# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
from dataclasses import dataclass
from typing import Match, Optional, Tuple, cast

from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.dependency_inference.rules import PythonInferSubsystem, import_rules
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PexCompletePlatformsField, PythonResolveField
from pants.core.goals.package import OutputPathField
from pants.engine.addresses import Address
from pants.engine.fs import GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    InvalidFieldException,
    InvalidTargetException,
    SecondaryOwnerMixin,
    StringField,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.source.filespec import Filespec
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap


class PythonAwsLambdaHandlerField(StringField, AsyncFieldMixin, SecondaryOwnerMixin):
    alias = "handler"
    required = True
    value: str
    help = softwrap(
        """
        Entry point to the AWS Lambda handler.

        You can specify a full module like 'path.to.module:handler_func' or use a shorthand to
        specify a file name, using the same syntax as the `sources` field, e.g.
        'lambda.py:handler_func'.

        You must use the file name shorthand for file arguments to work with this target.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> str:
        value = cast(str, super().compute_value(raw_value, address))
        if ":" not in value:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The `{cls.alias}` field in target at {address} must end in the format
                    `:my_handler_func`, but was {value}.
                    """
                )
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
    file_name_used: bool


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
        return ResolvedPythonAwsHandler(handler_val, file_name_used=False)

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
            softwrap(
                f"""
                Multiple files matched for the `{field_alias}` {repr(handler_val)} for the target
                {address}, but only one file expected.
                Are you using a glob, rather than a file name?

                All matching files: {list(handler_paths.files)}.
                """
            )
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
    return ResolvedPythonAwsHandler(f"{normalized_path}:{func}", file_name_used=True)


class PythonAwsLambdaDependencies(Dependencies):
    supports_transitive_excludes = True


class InjectPythonLambdaHandlerDependency(InjectDependenciesRequest):
    inject_for = PythonAwsLambdaDependencies


@rule(desc="Inferring dependency from the python_awslambda `handler` field")
async def inject_lambda_handler_dependency(
    request: InjectPythonLambdaHandlerDependency,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
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
    owners = await Get(
        PythonModuleOwners,
        PythonModuleOwnersRequest(
            module, resolve=original_tgt.target[PythonResolveField].normalized_value(python_setup)
        ),
    )
    address = original_tgt.target.address
    explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
        owners.ambiguous,
        address,
        # If the handler was specified as a file, like `app.py`, we know the module must
        # live in the python_awslambda's directory or subdirectory, so the owners must be ancestors.
        owners_must_be_ancestors=handler.file_name_used,
        import_reference="module",
        context=softwrap(
            f"""
            The python_awslambda target {address} has the field
            `handler={repr(original_tgt.target[PythonAwsLambdaHandlerField].value)}`,
            which maps to the Python module `{module}`"
            """
        ),
    )
    maybe_disambiguated = explicitly_provided_deps.disambiguated(
        owners.ambiguous, owners_must_be_ancestors=handler.file_name_used
    )
    unambiguous_owners = owners.unambiguous or (
        (maybe_disambiguated,) if maybe_disambiguated else ()
    )
    return InjectedDependencies(unambiguous_owners)


class PythonAwsLambdaIncludeRequirements(BoolField):
    alias = "include_requirements"
    default = True
    help = softwrap(
        """
        Whether to resolve requirements and include them in the Pex. This is most useful with Lambda
        Layers to make code uploads smaller when deps are in layers.
        https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
        """
    )


class PythonAwsLambdaRuntime(StringField):
    PYTHON_RUNTIME_REGEX = r"python(?P<major>\d)\.(?P<minor>\d+)"

    alias = "runtime"
    default = None
    help = softwrap(
        """
        The identifier of the AWS Lambda runtime to target (pythonX.Y).
        See https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html.
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
        PythonAwsLambdaDependencies,
        PythonAwsLambdaHandlerField,
        PythonAwsLambdaIncludeRequirements,
        PythonAwsLambdaRuntime,
        PexCompletePlatformsField,
        PythonResolveField,
    )
    help = softwrap(
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
        *import_rules(),
        UnionRule(InjectDependenciesRequest, InjectPythonLambdaHandlerDependency),
    )
