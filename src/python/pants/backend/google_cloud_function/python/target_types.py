# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import re
from dataclasses import dataclass
from enum import Enum
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
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.source.filespec import Filespec
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap


class PythonGoogleCloudFunctionHandlerField(StringField, AsyncFieldMixin, SecondaryOwnerMixin):
    alias = "handler"
    required = True
    value: str
    help = softwrap(
        """
        Entry point to the Google Cloud Function handler.

        You can specify a full module like 'path.to.module:handler_func' or use a shorthand to
        specify a file name, using the same syntax as the `sources` field, e.g.
        'cloud_function.py:handler_func'.

        You must use the file name shorthand for file arguments to work with this target.
        """
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
class ResolvedPythonGoogleHandler:
    val: str
    file_name_used: bool


@dataclass(frozen=True)
class ResolvePythonGoogleHandlerRequest:
    field: PythonGoogleCloudFunctionHandlerField


@rule(desc="Determining the handler for a `python_google_cloud_function` target")
async def resolve_python_google_cloud_function_handler(
    request: ResolvePythonGoogleHandlerRequest,
) -> ResolvedPythonGoogleHandler:
    handler_val = request.field.value
    field_alias = request.field.alias
    address = request.field.address
    path, _, func = handler_val.partition(":")

    # If it's already a module, simply use that. Otherwise, convert the file name into a module
    # path.
    if not path.endswith(".py"):
        return ResolvedPythonGoogleHandler(handler_val, file_name_used=False)

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
    return ResolvedPythonGoogleHandler(f"{normalized_path}:{func}", file_name_used=True)


class PythonGoogleCloudFunctionDependencies(Dependencies):
    supports_transitive_excludes = True


class InjectPythonCloudFunctionHandlerDependency(InjectDependenciesRequest):
    inject_for = PythonGoogleCloudFunctionDependencies


@rule(desc="Inferring dependency from the python_google_cloud_function `handler` field")
async def inject_cloud_function_handler_dependency(
    request: InjectPythonCloudFunctionHandlerDependency,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InjectedDependencies:
    if not python_infer_subsystem.entry_points:
        return InjectedDependencies()
    original_tgt = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            request.dependencies_field.address, description_of_origin="<infallible>"
        ),
    )
    explicitly_provided_deps, handler = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(original_tgt.target[Dependencies])),
        Get(
            ResolvedPythonGoogleHandler,
            ResolvePythonGoogleHandlerRequest(
                original_tgt.target[PythonGoogleCloudFunctionHandlerField]
            ),
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
        # live in the python_google_cloud_function's directory or subdirectory, so the owners must be ancestors.
        owners_must_be_ancestors=handler.file_name_used,
        import_reference="module",
        context=(
            f"The python_google_cloud_function target {address} has the field "
            f"`handler={repr(original_tgt.target[PythonGoogleCloudFunctionHandlerField].value)}`, which maps "
            f"to the Python module `{module}`"
        ),
    )
    maybe_disambiguated = explicitly_provided_deps.disambiguated(
        owners.ambiguous, owners_must_be_ancestors=handler.file_name_used
    )
    unambiguous_owners = owners.unambiguous or (
        (maybe_disambiguated,) if maybe_disambiguated else ()
    )
    return InjectedDependencies(unambiguous_owners)


class PythonGoogleCloudFunctionRuntimes(Enum):
    PYTHON_37 = "python37"
    PYTHON_38 = "python38"
    PYTHON_39 = "python39"


class PythonGoogleCloudFunctionRuntime(StringField):
    PYTHON_RUNTIME_REGEX = r"^python(?P<major>\d)(?P<minor>\d+)$"

    alias = "runtime"
    default = None
    valid_choices = PythonGoogleCloudFunctionRuntimes
    help = softwrap(
        """
        The identifier of the Google Cloud Function runtime to target (pythonXY). See
        https://cloud.google.com/functions/docs/concepts/python-runtime.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return None
        if not re.match(cls.PYTHON_RUNTIME_REGEX, value):
            raise InvalidFieldException(
                f"The `{cls.alias}` field in target at {address} must be of the form pythonXY, "
                f"but was {value}."
            )
        return value

    def to_interpreter_version(self) -> Optional[Tuple[int, int]]:
        """Returns the Python version implied by the runtime, as (major, minor)."""
        if self.value is None:
            return None
        mo = cast(Match, re.match(self.PYTHON_RUNTIME_REGEX, self.value))
        return int(mo.group("major")), int(mo.group("minor"))


class GoogleCloudFunctionTypes(Enum):
    EVENT = "event"
    HTTP = "http"


class PythonGoogleCloudFunctionType(StringField):

    alias = "type"
    required = True
    valid_choices = GoogleCloudFunctionTypes
    help = softwrap(
        """
        The trigger type of the cloud function. Can either be 'event' or 'http'.
        See https://cloud.google.com/functions/docs/concepts/python-runtime for reference to
        --trigger-http.
        """
    )


class PythonGoogleCloudFunction(Target):
    alias = "python_google_cloud_function"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        PythonGoogleCloudFunctionDependencies,
        PythonGoogleCloudFunctionHandlerField,
        PythonGoogleCloudFunctionRuntime,
        PexCompletePlatformsField,
        PythonGoogleCloudFunctionType,
        PythonResolveField,
    )
    help = softwrap(
        f"""
        A self-contained Python function suitable for uploading to Google Cloud Function.

        See {doc_url('google-cloud-function-python')}.
        """
    )

    def validate(self) -> None:
        if (
            self[PythonGoogleCloudFunctionRuntime].value is None
            and not self[PexCompletePlatformsField].value
        ):
            raise InvalidTargetException(
                f"The `{self.alias}` target {self.address} must specify either a "
                f"`{self[PythonGoogleCloudFunctionRuntime].alias}` or "
                f"`{self[PexCompletePlatformsField].alias}` or both."
            )


def rules():
    return (
        *collect_rules(),
        *import_rules(),
        UnionRule(InjectDependenciesRequest, InjectPythonCloudFunctionHandlerDependency),
    )
