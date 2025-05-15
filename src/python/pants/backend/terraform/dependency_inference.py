# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.pex import VenvPex, VenvPexProcess, create_venv_pex
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex import setup_venv_pex_process
from pants.backend.terraform.target_types import (
    TerraformBackendTarget,
    TerraformDependenciesField,
    TerraformDeploymentFieldSet,
    TerraformLockfileTarget,
    TerraformModuleSourcesField,
    TerraformVarFileTarget,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import DirGlobSpec, DirLiteralSpec, RawSpecs
from pants.core.target_types import LockfileTarget
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.build_files import resolve_address
from pants.engine.internals.graph import (
    determine_explicitly_provided_dependencies,
    hydrate_sources,
    resolve_targets,
)
from pants.engine.internals.native_engine import Address, AddressInput
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    DependenciesRequest,
    FieldSet,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Target,
)
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.resources import read_resource
from pants.util.strutil import bullet_list, softwrap


class TerraformHcl2Parser(PythonToolRequirementsBase):
    options_scope = "terraform-hcl2-parser"
    help_short = "Used to parse Terraform modules to infer their dependencies."

    # versions 4.3.2+ have parsing issues; bump once resolved
    default_requirements = ["python-hcl2>=3.0.5,<=4.3.0"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.terraform", "hcl2.lock")


@dataclass(frozen=True)
class ParserSetup:
    pex: VenvPex


@rule
async def setup_parser(hcl2_parser: TerraformHcl2Parser) -> ParserSetup:
    parser_script_content = read_resource("pants.backend.terraform", "hcl2_parser.py")
    if not parser_script_content:
        raise ValueError("Unable to find source to hcl2_parser.py wrapper script.")

    parser_content = FileContent(
        path="__pants_tf_parser.py", content=parser_script_content, is_executable=True
    )
    parser_digest = await create_digest(CreateDigest([parser_content]))

    parser_pex = await create_venv_pex(
        **implicitly(
            hcl2_parser.to_pex_request(
                main=EntryPoint(PurePath(parser_content.path).stem), sources=parser_digest
            )
        )
    )
    return ParserSetup(parser_pex)


@dataclass(frozen=True)
class ParseTerraformModuleSources:
    sources_digest: Digest
    paths: tuple[str, ...]


@rule
async def setup_process_for_parse_terraform_module_sources(
    request: ParseTerraformModuleSources, parser: ParserSetup
) -> Process:
    dir_paths = ", ".join(sorted(group_by_dir(request.paths).keys()))

    process = await setup_venv_pex_process(
        VenvPexProcess(
            parser.pex,
            argv=request.paths,
            input_digest=request.sources_digest,
            description=f"Parse Terraform module sources: {dir_paths}",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )
    return process


@dataclass(frozen=True)
class TerraformModuleDependenciesInferenceFieldSet(FieldSet):
    required_fields = (TerraformModuleSourcesField, TerraformDependenciesField)

    sources: TerraformModuleSourcesField
    dependencies: TerraformDependenciesField


class InferTerraformModuleDependenciesRequest(InferDependenciesRequest):
    infer_from = TerraformModuleDependenciesInferenceFieldSet


@dataclass(frozen=True)
class TerraformDeploymentDependenciesInferenceFieldSet(TerraformDeploymentFieldSet):
    pass


class InferTerraformDeploymentDependenciesRequest(InferDependenciesRequest):
    infer_from = TerraformDeploymentDependenciesInferenceFieldSet


def find_targets_of_type(tgts, of_type) -> tuple:
    if tgts:
        return tuple(e for e in tgts if isinstance(e, of_type))
    else:
        return ()


@dataclass(frozen=True)
class TerraformDeploymentInvocationFilesRequest:
    """TODO: is there a way to convert between FS? We could convert the inference FS to the deployment FS itself"""

    address: Address
    dependencies: TerraformDependenciesField


@dataclass(frozen=True)
class TerraformDeploymentInvocationFiles:
    """The files passed in to the invocation of `terraform`"""

    backend_configs: tuple[TerraformBackendTarget, ...]
    vars_files: tuple[TerraformVarFileTarget, ...]
    lockfile: LockfileTarget | None


@rule
async def get_terraform_backend_and_vars(
    field_set: TerraformDeploymentInvocationFilesRequest,
) -> TerraformDeploymentInvocationFiles:
    this_address = field_set.address

    explicit_deps = await determine_explicitly_provided_dependencies(
        **implicitly(DependenciesRequest(field_set.dependencies))
    )
    tgts_in_dir, explicit_deps_tgt = await concurrently(
        resolve_targets(
            **implicitly(
                RawSpecs(
                    description_of_origin="terraform infer deployment dependencies",
                    dir_literals=(DirLiteralSpec(this_address.spec_path),),
                )
            )
        ),
        resolve_targets(**implicitly(Addresses(explicit_deps.includes))),
    )
    return identify_terraform_backend_and_vars(explicit_deps_tgt, tgts_in_dir)


class InvalidLockfileException(Exception):
    @classmethod
    def too_many_lockfiles(
        cls, lockfiles: Iterable[TerraformLockfileTarget]
    ) -> InvalidLockfileException:
        addresses = sorted(tgt.address.spec for tgt in lockfiles)
        return cls(
            softwrap(
                f"""\
                A Terraform deployment has {len(addresses)} lockfiles supplied:
                {bullet_list(addresses)}
                Terraform requires at most 1 lockfile; it must be called `.terraform.lock.hcl`;
                and it must be in the same directory as the root module.

                Pants generates targets for Terraform lockfiles automatically.
                If you manually added `{TerraformLockfileTarget.alias}` targets, removing them should resolve this error.
                If you have not, please report this as a bug.
                """
            )
        )


def identify_terraform_backend_and_vars(
    explicit_deps: Sequence[Target], tgts_in_dir: Sequence[Target]
) -> TerraformDeploymentInvocationFiles:
    has_explicit_backend = find_targets_of_type(explicit_deps, TerraformBackendTarget)
    if not has_explicit_backend:
        # Note: Terraform does not support multiple backends, but dep inference isn't the place to enforce that
        backend_targets = find_targets_of_type(tgts_in_dir, TerraformBackendTarget)
    else:
        backend_targets = has_explicit_backend

    has_explicit_var = find_targets_of_type(explicit_deps, TerraformVarFileTarget)
    if not has_explicit_var:
        vars_targets = find_targets_of_type(tgts_in_dir, TerraformVarFileTarget)
    else:
        vars_targets = has_explicit_var

    lockfiles = find_targets_of_type(tgts_in_dir, TerraformLockfileTarget)
    if len(lockfiles) == 1:
        lockfile = lockfiles[0]
    elif len(lockfiles) > 1:
        # Unlikely, since we generate them based on a constant filename.
        # Indicates manual specification of targets
        raise InvalidLockfileException.too_many_lockfiles(lockfiles)
    else:
        lockfile = None

    return TerraformDeploymentInvocationFiles(backend_targets, vars_targets, lockfile)


async def _infer_dependencies_from_sources(
    request: InferTerraformModuleDependenciesRequest,
) -> list[Address]:
    """Parse the source code for references to other modules."""
    hydrated_sources = await hydrate_sources(
        HydrateSourcesRequest(request.field_set.sources), **implicitly()
    )
    paths = OrderedSet(
        filename for filename in hydrated_sources.snapshot.files if filename.endswith(".tf")
    )
    result = await execute_process_or_raise(
        **implicitly(
            ParseTerraformModuleSources(
                sources_digest=hydrated_sources.snapshot.digest,
                paths=tuple(paths),
            )
        )
    )
    candidate_spec_paths = [line for line in result.stdout.decode("utf-8").split("\n") if line]
    # For each path, see if there is a `terraform_module` target at the specified spec_path.
    candidate_targets = await resolve_targets(
        **implicitly(
            RawSpecs(
                dir_globs=tuple(DirGlobSpec(path) for path in candidate_spec_paths),
                unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
                description_of_origin="the `terraform_module` dependency inference rule",
            )
        )
    )
    # TODO: Need to either implement the standard ambiguous dependency logic or ban >1 terraform_module
    # per directory.
    terraform_module_addresses = [
        tgt.address for tgt in candidate_targets if tgt.has_field(TerraformModuleSourcesField)
    ]
    return terraform_module_addresses


async def _infer_lockfile(request: InferTerraformModuleDependenciesRequest) -> list[Address]:
    """Pull in the lockfile for a Terraform module.

    This is necessary for `terraform validate`.
    """
    invocation_files = await get_terraform_backend_and_vars(
        TerraformDeploymentInvocationFilesRequest(
            request.field_set.address, request.field_set.dependencies
        )
    )
    if invocation_files.lockfile:
        return [invocation_files.lockfile.address]
    else:
        return []


@rule
async def infer_terraform_module_dependencies(
    request: InferTerraformModuleDependenciesRequest,
) -> InferredDependencies:
    terraform_module_addresses = await _infer_dependencies_from_sources(request)
    lockfile_address = await _infer_lockfile(request)

    return InferredDependencies([*terraform_module_addresses, *lockfile_address])


@rule
async def infer_terraform_deployment_dependencies(
    request: InferTerraformDeploymentDependenciesRequest,
) -> InferredDependencies:
    root_module_address_input = request.field_set.root_module.to_address_input()
    root_module = await resolve_address(**implicitly({root_module_address_input: AddressInput}))
    deps = [root_module]

    invocation_files = await get_terraform_backend_and_vars(
        TerraformDeploymentInvocationFilesRequest(
            request.field_set.address, request.field_set.dependencies
        )
    )
    deps.extend(e.address for e in invocation_files.backend_configs)
    deps.extend(e.address for e in invocation_files.vars_files)
    # lockfile is attached to the module itself

    return InferredDependencies(deps)


def rules():
    return [
        *collect_rules(),
        *pex_rules(),
        UnionRule(InferDependenciesRequest, InferTerraformModuleDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferTerraformDeploymentDependenciesRequest),
    ]
