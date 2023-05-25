# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Tuple

from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.terraform.target_types import TerraformModuleSourcesField
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.utils import terraform_arg, terraform_relpath
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import DirGlobSpec, RawSpecs
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import EMPTY_DIGEST, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    FieldSet,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.resources import read_resource


class TerraformHcl2Parser(PythonToolRequirementsBase):
    options_scope = "terraform-hcl2-parser"
    help = "Used to parse Terraform modules to infer their dependencies."

    default_requirements = ["python-hcl2>=3.0.5,<5"]

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
    parser_digest = await Get(Digest, CreateDigest([parser_content]))

    parser_pex = await Get(
        VenvPex,
        PexRequest,
        hcl2_parser.to_pex_request(
            main=EntryPoint(PurePath(parser_content.path).stem), sources=parser_digest
        ),
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

    process = await Get(
        Process,
        VenvPexProcess(
            parser.pex,
            argv=request.paths,
            input_digest=request.sources_digest,
            description=f"Parse Terraform module sources: {dir_paths}",
            level=LogLevel.DEBUG,
        ),
    )
    return process


@dataclass(frozen=True)
class TerraformModuleDependenciesInferenceFieldSet(FieldSet):
    required_fields = (TerraformModuleSourcesField,)

    sources: TerraformModuleSourcesField


class InferTerraformModuleDependenciesRequest(InferDependenciesRequest):
    infer_from = TerraformModuleDependenciesInferenceFieldSet


@rule
async def infer_terraform_module_dependencies(
    request: InferTerraformModuleDependenciesRequest,
) -> InferredDependencies:
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.field_set.sources))

    paths = OrderedSet(
        filename for filename in hydrated_sources.snapshot.files if filename.endswith(".tf")
    )
    result = await Get(
        ProcessResult,
        ParseTerraformModuleSources(
            sources_digest=hydrated_sources.snapshot.digest,
            paths=tuple(paths),
        ),
    )
    candidate_spec_paths = [line for line in result.stdout.decode("utf-8").split("\n") if line]

    # For each path, see if there is a `terraform_module` target at the specified spec_path.
    candidate_targets = await Get(
        Targets,
        RawSpecs(
            dir_globs=tuple(DirGlobSpec(path) for path in candidate_spec_paths),
            unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
            description_of_origin="the `terraform_module` dependency inference rule",
        ),
    )
    # TODO: Need to either implement the standard ambiguous dependency logic or ban >1 terraform_module
    # per directory.
    terraform_module_addresses = [
        tgt.address for tgt in candidate_targets if tgt.has_field(TerraformModuleSourcesField)
    ]
    return InferredDependencies(terraform_module_addresses)


@dataclass(frozen=True)
class GetTerraformDependenciesRequest:
    source_files: SourceFiles
    directories: Tuple[str, ...]
    backend_config: SourceFiles

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False


@dataclass(frozen=True)
class TerraformDependencies:
    fetched_deps: Tuple[Tuple[str, Digest], ...]


@rule
async def get_terraform_providers(
    req: GetTerraformDependenciesRequest,
) -> TerraformDependencies:
    args = ["init"]
    if req.backend_config.files:
        args.append(
            terraform_arg(
                "-backend-config",
                terraform_relpath(req.directories[0], req.backend_config.files[0]),
            )
        )
        backend_digest = req.backend_config.snapshot.digest
    else:
        backend_digest = EMPTY_DIGEST

    args.append(terraform_arg("-backend", str(req.initialise_backend)))

    with_backend_config = await Get(
        Digest, MergeDigests([req.source_files.snapshot.digest, backend_digest])
    )

    # TODO: Does this need to be a MultiGet? I think we will now always get one directory
    fetched_deps = await MultiGet(
        Get(
            FallibleProcessResult,
            TerraformProcess(
                args=tuple(args),
                input_digest=with_backend_config,
                output_files=(".terraform.lock.hcl",),
                output_directories=(".terraform",),
                description="Run `terraform init` to fetch dependencies",
                chdir=directory,
            ),
        )
        for directory in req.directories
    )

    return TerraformDependencies(
        tuple(zip(req.directories, (x.output_digest for x in fetched_deps)))
    )


def rules():
    return [
        *collect_rules(),
        *pex_rules(),
        UnionRule(InferDependenciesRequest, InferTerraformModuleDependenciesRequest),
    ]
