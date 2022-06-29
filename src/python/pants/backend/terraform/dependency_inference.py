# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pkgutil
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.terraform.target_types import TerraformModuleSourcesField
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import DirGlobSpec, RawSpecs
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.tailor import group_by_dir
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet


class TerraformHcl2Parser(PythonToolRequirementsBase):
    options_scope = "terraform-hcl2-parser"
    help = "Used to parse Terraform modules to infer their dependencies."

    default_version = "python-hcl2==3.0.5"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.terraform", "hcl2.lock")
    default_lockfile_path = "src/python/pants/backend/terraform/hcl2.lock"
    default_lockfile_url = git_url(default_lockfile_path)


class TerraformHcl2ParserLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = TerraformHcl2Parser.options_scope


@rule
def setup_lockfile_request(
    _: TerraformHcl2ParserLockfileSentinel,
    hcl2_parser: TerraformHcl2Parser,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        hcl2_parser, use_pex=python_setup.generate_lockfiles_with_pex
    )


@dataclass(frozen=True)
class ParserSetup:
    pex: VenvPex


@rule
async def setup_parser(hcl2_parser: TerraformHcl2Parser) -> ParserSetup:
    parser_script_content = pkgutil.get_data("pants.backend.terraform", "hcl2_parser.py")
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


class InferTerraformModuleDependenciesRequest(InferDependenciesRequest):
    infer_from = TerraformModuleSourcesField


@rule
async def infer_terraform_module_dependencies(
    request: InferTerraformModuleDependenciesRequest,
) -> InferredDependencies:
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))

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


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(InferDependenciesRequest, InferTerraformModuleDependenciesRequest),
        UnionRule(GenerateToolLockfileSentinel, TerraformHcl2ParserLockfileSentinel),
    ]
