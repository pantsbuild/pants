# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.docker.target_types import DockerImageSourceField
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
from pants.util.resources import read_resource

_DOCKERFILE_SANDBOX_TOOL = "dockerfile_wrapper_script.py"
_DOCKERFILE_PACKAGE = "pants.backend.docker.subsystems"


class DockerfileParser(PythonToolRequirementsBase):
    options_scope = "dockerfile-parser"
    help = "Used to parse Dockerfile build specs to infer their dependencies."

    default_version = "dockerfile==3.2.0"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = (_DOCKERFILE_PACKAGE, "dockerfile.lock")
    default_lockfile_path = f"src/python/{_DOCKERFILE_PACKAGE.replace('.', '/')}/dockerfile.lock"
    default_lockfile_url = git_url(default_lockfile_path)


class DockerfileParserLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = DockerfileParser.options_scope


@rule
def setup_lockfile_request(
    _: DockerfileParserLockfileSentinel,
    dockerfile_parser: DockerfileParser,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        dockerfile_parser, use_pex=python_setup.generate_lockfiles_with_pex
    )


@dataclass(frozen=True)
class ParserSetup:
    pex: VenvPex


@rule
async def setup_parser(dockerfile_parser: DockerfileParser) -> ParserSetup:
    parser_script_content = read_resource(_DOCKERFILE_PACKAGE, _DOCKERFILE_SANDBOX_TOOL)
    if not parser_script_content:
        raise ValueError(
            f"Unable to find source to {_DOCKERFILE_SANDBOX_TOOL!r} in {_DOCKERFILE_PACKAGE}."
        )

    parser_content = FileContent(
        path="__pants_df_parser.py",
        content=parser_script_content,
        is_executable=True,
    )
    parser_digest = await Get(Digest, CreateDigest([parser_content]))

    parser_pex = await Get(
        VenvPex,
        PexRequest,
        dockerfile_parser.to_pex_request(
            main=EntryPoint(PurePath(parser_content.path).stem), sources=parser_digest
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


class DockerfileInfoError(Exception):
    pass


@dataclass(frozen=True)
class DockerfileInfo:
    address: Address
    digest: Digest

    # Data from the parsed Dockerfile, keep in sync with
    # `dockerfile_wrapper_script.py:ParsedDockerfileInfo`:
    source: str
    build_args: DockerBuildArgs = DockerBuildArgs()
    copy_source_paths: tuple[str, ...] = ()
    from_image_build_args: DockerBuildArgs = DockerBuildArgs()
    version_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DockerfileInfoRequest:
    address: Address


@rule
async def parse_dockerfile(request: DockerfileInfoRequest) -> DockerfileInfo:
    wrapped_target = await Get(
        WrappedTarget, WrappedTargetRequest(request.address, description_of_origin="<infallible>")
    )
    target = wrapped_target.target
    sources = await Get(
        HydratedSources,
        HydrateSourcesRequest(
            target.get(SourcesField),
            for_sources_types=(DockerImageSourceField,),
            enable_codegen=True,
        ),
    )

    dockerfiles = sources.snapshot.files
    assert len(dockerfiles) == 1, (
        f"Internal error: Expected a single source file to Dockerfile parse request {request}, "
        f"got: {dockerfiles}."
    )

    result = await Get(
        ProcessResult,
        DockerfileParseRequest(
            sources.snapshot.digest,
            dockerfiles,
        ),
    )

    try:
        raw_output = result.stdout.decode("utf-8")
        outputs = json.loads(raw_output)
        assert len(outputs) == len(dockerfiles)
    except Exception as e:
        raise DockerfileInfoError(
            f"Unexpected failure to parse Dockerfiles: {', '.join(dockerfiles)}, "
            f"for the {request.address} target: {e}\nDockerfile parser output:\n{raw_output}"
        ) from e

    info = outputs[0]
    try:
        return DockerfileInfo(
            address=request.address,
            digest=sources.snapshot.digest,
            source=info["source"],
            build_args=DockerBuildArgs.from_strings(
                *info["build_args"], duplicates_must_match=True
            ),
            copy_source_paths=tuple(info["copy_source_paths"]),
            from_image_build_args=DockerBuildArgs.from_strings(
                *info["from_image_build_args"], duplicates_must_match=True
            ),
            version_tags=tuple(info["version_tags"]),
        )
    except ValueError as e:
        raise DockerfileInfoError(
            f"Error while parsing {info['source']} for the {request.address} target: {e}"
        ) from e


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        *pex.rules(),
        UnionRule(GenerateToolLockfileSentinel, DockerfileParserLockfileSentinel),
    )
