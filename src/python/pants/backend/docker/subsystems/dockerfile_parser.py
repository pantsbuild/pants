# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pkgutil
from dataclasses import dataclass
from pathlib import PurePath
from typing import Generator

from pants.backend.docker.target_types import DockerImageSourceField
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
from pants.util.logging import LogLevel

_DOCKERFILE_SANDBOX_TOOL = "dockerfile_wrapper_script.py"
_DOCKERFILE_PACKAGE = "pants.backend.docker.subsystems"


class DockerfileParser(PythonToolRequirementsBase):
    options_scope = "dockerfile-parser"
    help = "Used to parse Dockerfile build specs to infer their dependencies."

    default_version = "dockerfile==3.2.0"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7"]

    register_lockfile = True
    default_lockfile_resource = (_DOCKERFILE_PACKAGE, "dockerfile_lockfile.txt")
    default_lockfile_path = (
        f"src/python/{_DOCKERFILE_PACKAGE.replace('.', '/')}/dockerfile_lockfile.txt"
    )
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
    parser_script_content = pkgutil.get_data(_DOCKERFILE_PACKAGE, _DOCKERFILE_SANDBOX_TOOL)
    if not parser_script_content:
        raise ValueError(
            "Unable to find source to {_DOCKERFILE_SANDBOX_TOOL!r} in {_DOCKERFILE_PACKAGE}."
        )

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
    args: tuple[str, ...]


@rule
async def setup_process_for_parse_dockerfile(
    request: DockerfileParseRequest, parser: ParserSetup
) -> Process:
    process = await Get(
        Process,
        VenvPexProcess(
            parser.pex,
            argv=request.args,
            description="Parse Dockerfile.",
            input_digest=request.sources_digest,
            level=LogLevel.DEBUG,
        ),
    )
    return process


@dataclass(frozen=True)
class DockerfileInfo:
    source: str = ""
    putative_target_addresses: tuple[str, ...] = ()
    version_tags: tuple[str, ...] = ()


def split_iterable(
    sep: str, obj: list[str] | tuple[str, ...]
) -> Generator[tuple[str, ...], None, None]:
    while sep in obj:
        idx = obj.index(sep)
        yield tuple(obj[:idx])
        obj = obj[idx + 1 :]
    yield tuple(obj)


@rule
async def parse_dockerfile(source: DockerImageSourceField) -> DockerfileInfo:
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(source))
    result = await Get(
        ProcessResult,
        DockerfileParseRequest(
            hydrated_sources.snapshot.digest,
            ("version-tags,putative-targets", *hydrated_sources.snapshot.files),
        ),
    )

    output = result.stdout.decode("utf-8").strip().split("\n")
    version_tags, putative_targets = split_iterable("---", output)

    # There can only be a single file in the snapshot, due to the
    # DockerImageSourceField.expected_num_files == 1.
    return DockerfileInfo(
        source=hydrated_sources.snapshot.files[0],
        putative_target_addresses=putative_targets,
        version_tags=version_tags,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(PythonToolLockfileSentinel, DockerfileParserLockfileSentinel),
    )
