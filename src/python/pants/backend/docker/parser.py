# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pkgutil
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.docker.target_types import DockerImageSources
from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url


class DockerfileParser(PythonToolRequirementsBase):
    options_scope = "dockerfile-parser"
    help = "Used to parse Dockerfile build specs to infer their dependencies."

    default_version = "dockerfile==3.2.0"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6.1"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.docker", "dockerfile_lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/docker/dockerfile_lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)


class DockerfileParserLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = DockerfileParser.options_scope


@rule
def setup_lockfile_request(
    _: DockerfileParserLockfileSentinel, dockerfile_parser: DockerfileParser
) -> PythonLockfileRequest:
    return PythonLockfileRequest.from_tool(dockerfile_parser)


@dataclass(frozen=True)
class ParserSetup:
    pex: VenvPex


@rule
async def setup_parser(dockerfile_parser: DockerfileParser) -> ParserSetup:
    parser_script_content = pkgutil.get_data("pants.backend.docker", "dockerfile_parser.py")
    if not parser_script_content:
        raise ValueError("Unable to find source to dockerfile_parser.py wrapper script.")

    parser_content = FileContent(
        path="__pants_df_parser.py",
        content=parser_script_content,
        is_executable=True,
    )

    parser_digest = await Get(Digest, CreateDigest([parser_content]))

    parser_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="dockerfile_parser.pex",
            internal_only=True,
            requirements=dockerfile_parser.pex_requirements(),
            interpreter_constraints=dockerfile_parser.interpreter_constraints,
            main=EntryPoint(PurePath(parser_content.path).stem),
            sources=parser_digest,
        ),
    )

    return ParserSetup(parser_pex)


@dataclass(frozen=True)
class DockerfileParseRequest:
    sources_digest: Digest
    paths: tuple[str, ...]


@rule
async def setup_process_for_parse_dockerfile(
    request: DockerfileParseRequest, parser: ParserSetup
) -> Process:
    process = await Get(
        Process,
        VenvPexProcess(
            parser.pex,
            argv=request.paths,
            input_digest=request.sources_digest,
            description="Parse Dockerfile.",
        ),
    )
    return process


@dataclass(frozen=True)
class DockerfileInfo:
    putative_target_addresses: tuple[str, ...] = ()


@rule
async def parse_dockerfile(sources: DockerImageSources) -> DockerfileInfo:
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(sources))
    result = await Get(
        ProcessResult,
        DockerfileParseRequest(hydrated_sources.snapshot.digest, hydrated_sources.snapshot.files),
    )

    putative_target_addresses = [line for line in result.stdout.decode("utf-8").split("\n") if line]

    return DockerfileInfo(
        putative_target_addresses=tuple(putative_target_addresses),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(PythonToolLockfileSentinel, DockerfileParserLockfileSentinel),
    )
