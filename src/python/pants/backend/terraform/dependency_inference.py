# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.terraform.target_types import TerraformModuleSources
from pants.base.specs import AddressSpecs, MaybeEmptySiblingAddresses
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
from pants.util.ordered_set import OrderedSet

PARSER = FileContent(
    "__pants_tf_parser.py",
    textwrap.dedent(
        """\
    import sys

    import hcl2

    # PurePath does not have the Path.resolve method which resolves ".." components, thus we need to
    # code our own version for PurePath's.
    def resolve_pure_path(base: PurePath, relative_path: PurePath) -> PurePath:
        parts = list(base.parts)
        for component in relative_path.parts:
            if component == ".":
                pass
            elif component == "..":
                if not parts:
                    raise ValueError(f"Relative path {relative_path} escapes from path {base}.")
                parts.pop()
            else:
                parts.append(component)

        return PurePath(*parts)


    def extract_module_source_paths(path: PurePath, raw_content: bytes) -> set[str]:
        content = raw_content.decode("utf-8")
        parsed_content = hcl2.loads(content)

        # Note: The `module` key is a list where each entry is a dict with a single entry where the key is the
        # module name and the values are a dict for that module's actual values.
        paths = set()
        for wrapped_module in parsed_content.get("module", []):
            values = list(wrapped_module.values())[
                0
            ]  # the module is the sole entry in `wrapped_module`
            source = values.get("source", "")

            # Local paths to modules must begin with "." or ".." as per
            # https://www.terraform.io/docs/language/modules/sources.html#local-paths.
            if source.startswith("./") or source.startswith("../"):
                try:
                    resolved_path = resolve_pure_path(path, PurePath(source))
                    paths.add(str(resolved_path))
                except ValueError:
                    pass

        return paths


    paths = set()
    for filename in sys.argv[1:]:
        paths |= extract_module_source_paths(PurePath(filename).parent, entry.content)

    for path in paths:
        print(path)
    """
    ).encode("utf-8"),
    is_executable=True,
)


class PythonHcl2Subsystem(PythonToolRequirementsBase):
    options_scope = "python-hcl2"
    help = "Used to parse Terraform modules to infer their dependencies."

    default_version = "python-hcl2==3.0.1"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7"]


@dataclass(frozen=True)
class ParserSetup:
    pex: VenvPex


@rule
async def setup_parser(hcl2_subsystem: PythonHcl2Subsystem) -> ParserSetup:
    parser_digest = await Get(Digest, CreateDigest([PARSER]))

    parser_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="tf_parser.pex",
            internal_only=True,
            requirements=hcl2_subsystem.pex_requirements(),
            interpreter_constraints=hcl2_subsystem.interpreter_constraints,
            main=EntryPoint(PurePath(PARSER.path).stem),
            sources=parser_digest,
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
    process = await Get(
        Process,
        VenvPexProcess(
            parser.pex,
            argv=request.paths,
            input_digest=request.sources_digest,
            description="Parse Terraform module sources.",
        ),
    )
    return process


class InferTerraformModuleDependenciesRequest(InferDependenciesRequest):
    infer_from = TerraformModuleSources


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
        Targets, AddressSpecs([MaybeEmptySiblingAddresses(path) for path in candidate_spec_paths])
    )
    terraform_module_addresses = [
        tgt.address for tgt in candidate_targets if tgt.has_field(TerraformModuleSources)
    ]
    return InferredDependencies(terraform_module_addresses, sibling_dependencies_inferrable=False)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferTerraformModuleDependenciesRequest),
    ]
