# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Function-as-a-service (FaaS) support like AWS Lambda and Google Cloud Functions."""

from __future__ import annotations

import logging
import os.path
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, cast

from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.dependency_inference.rules import import_rules
from pants.backend.python.dependency_inference.subsystem import (
    AmbiguityResolution,
    PythonInferSubsystem,
)
from pants.backend.python.subsystems.lambdex import Lambdex
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PexCompletePlatformsField,
    PexLayout,
    PythonResolveField,
)
from pants.backend.python.util_rules.pex import (
    CompletePlatforms,
    Pex,
    PexPlatforms,
    PexRequest,
    VenvPex,
    VenvPexProcess,
)
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.pex_from_targets import rules as pex_from_targets_rules
from pants.backend.python.util_rules.pex_venv import PexVenv, PexVenvLayout, PexVenvRequest
from pants.backend.python.util_rules.pex_venv import rules as pex_venv_rules
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, OutputPathField
from pants.engine.addresses import Address, UnparsedAddressInputs
from pants.engine.fs import (
    CreateDigest,
    Digest,
    FileContent,
    GlobMatchErrorBehavior,
    PathGlobs,
    Paths,
)
from pants.engine.platform import Platform
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AsyncFieldMixin,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    InvalidFieldException,
    SecondaryOwnerMixin,
    StringField,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.source.filespec import Filespec
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import bin_name
from pants.util.strutil import help_text

logger = logging.getLogger(__name__)


class PythonFaaSHandlerField(StringField, AsyncFieldMixin, SecondaryOwnerMixin):
    alias = "handler"
    required = True
    value: str
    help = help_text(
        """
        You can specify a full module like `'path.to.module:handler_func'` or use a shorthand to
        specify a file name, using the same syntax as the `sources` field, e.g.
        `'cloud_function.py:handler_func'`.

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
class ResolvedPythonFaaSHandler:
    module: str
    func: str
    file_name_used: bool


@dataclass(frozen=True)
class ResolvePythonFaaSHandlerRequest:
    field: PythonFaaSHandlerField


@rule(desc="Determining the handler for a python FaaS target")
async def resolve_python_faas_handler(
    request: ResolvePythonFaaSHandlerRequest,
) -> ResolvedPythonFaaSHandler:
    handler_val = request.field.value
    field_alias = request.field.alias
    address = request.field.address
    path, _, func = handler_val.partition(":")

    # If it's already a module, simply use that. Otherwise, convert the file name into a module
    # path.
    if not path.endswith(".py"):
        return ResolvedPythonFaaSHandler(module=path, func=func, file_name_used=False)

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
    return ResolvedPythonFaaSHandler(module=normalized_path, func=func, file_name_used=True)


class PythonFaaSDependencies(Dependencies):
    supports_transitive_excludes = True


@dataclass(frozen=True)
class PythonFaaSHandlerInferenceFieldSet(FieldSet):
    required_fields = (
        PythonFaaSDependencies,
        PythonFaaSHandlerField,
        PythonResolveField,
    )

    dependencies: PythonFaaSDependencies
    handler: PythonFaaSHandlerField
    resolve: PythonResolveField


class InferPythonFaaSHandlerDependency(InferDependenciesRequest):
    infer_from = PythonFaaSHandlerInferenceFieldSet


@rule(desc="Inferring dependency from the python FaaS `handler` field")
async def infer_faas_handler_dependency(
    request: InferPythonFaaSHandlerDependency,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InferredDependencies:
    if not python_infer_subsystem.entry_points:
        return InferredDependencies([])

    explicitly_provided_deps, handler = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)),
        Get(
            ResolvedPythonFaaSHandler,
            ResolvePythonFaaSHandlerRequest(request.field_set.handler),
        ),
    )

    # Only set locality if needed, to avoid unnecessary rule graph memoization misses.
    # When set, use the source root, which is useful in practice, but incurs fewer memoization
    # misses than using the full spec_path.
    locality = None
    if python_infer_subsystem.ambiguity_resolution == AmbiguityResolution.by_source_root:
        source_root = await Get(
            SourceRoot, SourceRootRequest, SourceRootRequest.for_address(request.field_set.address)
        )
        locality = source_root.path

    owners = await Get(
        PythonModuleOwners,
        PythonModuleOwnersRequest(
            handler.module,
            resolve=request.field_set.resolve.normalized_value(python_setup),
            locality=locality,
        ),
    )
    address = request.field_set.address
    explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
        owners.ambiguous,
        address,
        # If the handler was specified as a file, like `app.py`, we know the module must
        # live in the python_google_cloud_function's directory or subdirectory, so the owners must be ancestors.
        owners_must_be_ancestors=handler.file_name_used,
        import_reference="module",
        context=(
            f"The target {address} has the field "
            f"`handler={repr(request.field_set.handler.value)}`, which maps "
            f"to the Python module `{handler.module}`"
        ),
    )
    maybe_disambiguated = explicitly_provided_deps.disambiguated(
        owners.ambiguous, owners_must_be_ancestors=handler.file_name_used
    )
    unambiguous_owners = owners.unambiguous or (
        (maybe_disambiguated,) if maybe_disambiguated else ()
    )
    return InferredDependencies(unambiguous_owners)


class PythonFaaSCompletePlatforms(PexCompletePlatformsField):
    help = help_text(
        f"""
        {PexCompletePlatformsField.help}

        N.B.: If specifying `complete_platforms` to work around packaging failures encountered when
        using the `runtime` field, ensure you delete the `runtime` field from the target.
        """
    )


class PythonFaaSRuntimeField(StringField, ABC):
    alias = "runtime"
    default = None

    @abstractmethod
    def to_interpreter_version(self) -> None | tuple[int, int]:
        """Returns the Python version implied by the runtime, as (major, minor)."""

    def to_platform_string(self) -> None | str:
        # We hardcode the platform value to the appropriate one for each FaaS runtime.
        # (Running the "hello world" cloud function in the example code will report the platform, and can be
        # used to verify correctness of these platform strings.)
        interpreter_version = self.to_interpreter_version()
        if interpreter_version is None:
            return None

        py_major, py_minor = interpreter_version
        platform_str = f"linux_x86_64-cp-{py_major}{py_minor}-cp{py_major}{py_minor}"
        # set pymalloc ABI flag - this was removed in python 3.8 https://bugs.python.org/issue36707
        if py_major <= 3 and py_minor < 8:
            platform_str += "m"
        return platform_str


@rule
async def digest_complete_platforms(
    complete_platforms: PythonFaaSCompletePlatforms,
) -> CompletePlatforms:
    return await Get(
        CompletePlatforms, UnparsedAddressInputs, complete_platforms.to_unparsed_address_inputs()
    )


@dataclass(frozen=True)
class BuildLambdexRequest:
    address: Address
    target_name: str

    complete_platforms: PythonFaaSCompletePlatforms
    handler: PythonFaaSHandlerField
    output_path: OutputPathField
    runtime: PythonFaaSRuntimeField

    include_requirements: bool

    script_handler: None | str
    script_module: None | str

    handler_log_message: str


@rule
async def build_lambdex(
    request: BuildLambdexRequest,
    lambdex: Lambdex,
    platform: Platform,
) -> BuiltPackage:
    if platform.is_macos:
        logger.warning(
            f"`{request.target_name}` targets built on macOS may fail to build. If your function uses any"
            " third-party dependencies without binary wheels (bdist) for Linux available, it will"
            " fail to build. If this happens, you will either need to update your dependencies to"
            " only use dependencies with pre-built wheels, or find a Linux environment to run"
            f" {bin_name()} package. (See https://realpython.com/python-wheels/ for more about"
            " wheels.)\n\n(If the build does not raise an exception, it's safe to use macOS.)"
        )
    lambdex.warn_for_layout(request.target_name)

    output_filename = request.output_path.value_or_default(
        # FaaS typically use the .zip suffix, so we use that instead of .pex.
        file_ending="zip",
    )

    platform_str = request.runtime.to_platform_string()
    pex_platforms = [platform_str] if platform_str else []

    additional_pex_args = (
        # Ensure we can resolve manylinux wheels in addition to any AMI-specific wheels.
        "--manylinux=manylinux2014",
        # When we're executing Pex on Linux, allow a local interpreter to be resolved if
        # available and matching the AMI platform.
        "--resolve-local-platforms",
    )

    complete_platforms = await Get(
        CompletePlatforms, PythonFaaSCompletePlatforms, request.complete_platforms
    )

    pex_request = PexFromTargetsRequest(
        addresses=[request.address],
        internal_only=False,
        include_requirements=request.include_requirements,
        output_filename=output_filename,
        platforms=PexPlatforms(pex_platforms),
        complete_platforms=complete_platforms,
        additional_args=additional_pex_args,
        additional_lockfile_args=additional_pex_args,
        warn_for_transitive_files_targets=True,
    )
    lambdex_request = lambdex.to_pex_request()

    lambdex_pex, pex_result, handler, transitive_targets = await MultiGet(
        Get(VenvPex, PexRequest, lambdex_request),
        Get(Pex, PexFromTargetsRequest, pex_request),
        Get(ResolvedPythonFaaSHandler, ResolvePythonFaaSHandlerRequest(request.handler)),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.address])),
    )

    lambdex_args = ["build", "-e", f"{handler.module}:{handler.func}", output_filename]
    if request.script_handler:
        lambdex_args.extend(("-H", request.script_handler))
    if request.script_module:
        lambdex_args.extend(("-M", request.script_module))

    # NB: Lambdex modifies its input pex in-place, so the input file is also the output file.
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            lambdex_pex,
            argv=tuple(lambdex_args),
            input_digest=pex_result.digest,
            output_files=(output_filename,),
            description=f"Setting up handler in {output_filename}",
        ),
    )

    extra_log_data: list[tuple[str, str]] = []
    if request.runtime.value:
        extra_log_data.append(("Runtime", request.runtime.value))
    extra_log_data.extend(("Complete platform", path) for path in complete_platforms)
    extra_log_data.append(("Handler", request.handler_log_message))

    first_column_width = 4 + max(len(header) for header, _ in extra_log_data)
    artifact = BuiltPackageArtifact(
        output_filename,
        extra_log_lines=tuple(
            f"{header.rjust(first_column_width, ' ')}: {data}" for header, data in extra_log_data
        ),
    )
    return BuiltPackage(digest=result.output_digest, artifacts=(artifact,))


@dataclass(frozen=True)
class BuildPythonFaaSRequest:
    address: Address
    target_name: str

    complete_platforms: PythonFaaSCompletePlatforms
    handler: PythonFaaSHandlerField
    output_path: OutputPathField
    runtime: PythonFaaSRuntimeField

    include_requirements: bool

    reexported_handler_module: str
    log_only_reexported_handler_func: bool = False


@rule
async def build_python_faas(
    request: BuildPythonFaaSRequest,
) -> BuiltPackage:
    platform_str = request.runtime.to_platform_string()
    pex_platforms = PexPlatforms([platform_str] if platform_str else [])

    additional_pex_args = (
        # Ensure we can resolve manylinux wheels in addition to any AMI-specific wheels.
        "--manylinux=manylinux2014",
        # When we're executing Pex on Linux, allow a local interpreter to be resolved if
        # available and matching the AMI platform.
        "--resolve-local-platforms",
    )

    complete_platforms, handler = await MultiGet(
        Get(CompletePlatforms, PythonFaaSCompletePlatforms, request.complete_platforms),
        Get(ResolvedPythonFaaSHandler, ResolvePythonFaaSHandlerRequest(request.handler)),
    )

    # TODO: improve diagnostics if there's more than one platform/complete_platform

    # synthesise a source file that gives a fixed handler path, no matter what the entry point is:
    # some platforms require a certain name (e.g. GCF), and even on others, giving a fixed name
    # means users don't need to duplicate the entry_point config in both the pants BUILD file and
    # infrastructure definitions (the latter can always use the same names, for every lambda).
    reexported_handler_file = f"{request.reexported_handler_module}.py"
    reexported_handler_func = "handler"
    reexported_handler_content = (
        f"from {handler.module} import {handler.func} as {reexported_handler_func}"
    )
    additional_sources = await Get(
        Digest,
        CreateDigest([FileContent(reexported_handler_file, reexported_handler_content.encode())]),
    )

    repository_filename = "faas_repository.pex"
    pex_request = PexFromTargetsRequest(
        addresses=[request.address],
        internal_only=False,
        include_requirements=request.include_requirements,
        output_filename=repository_filename,
        platforms=pex_platforms,
        complete_platforms=complete_platforms,
        layout=PexLayout.PACKED,
        additional_args=additional_pex_args,
        additional_lockfile_args=additional_pex_args,
        additional_sources=additional_sources,
        warn_for_transitive_files_targets=True,
    )

    pex_result = await Get(Pex, PexFromTargetsRequest, pex_request)

    output_filename = request.output_path.value_or_default(file_ending="zip")

    result = await Get(
        PexVenv,
        PexVenvRequest(
            pex=pex_result,
            layout=PexVenvLayout.FLAT_ZIPPED,
            platforms=pex_platforms,
            complete_platforms=complete_platforms,
            output_path=Path(output_filename),
            description=f"Build {request.target_name} artifact for {request.address}",
        ),
    )

    if request.log_only_reexported_handler_func:
        handler_text = reexported_handler_func
    else:
        handler_text = f"{request.reexported_handler_module}.{reexported_handler_func}"

    artifact = BuiltPackageArtifact(
        output_filename,
        extra_log_lines=(f"    Handler: {handler_text}",),
    )
    return BuiltPackage(digest=result.digest, artifacts=(artifact,))


def rules():
    return (
        *collect_rules(),
        *import_rules(),
        *pex_venv_rules(),
        *pex_from_targets_rules(),
        UnionRule(InferDependenciesRequest, InferPythonFaaSHandlerDependency),
    )
