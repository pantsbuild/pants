# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pkgutil
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterator

from pants.backend.docker.target_types import DockerImageSourceField
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
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
from pants.engine.target import HydratedSources, HydrateSourcesRequest, SourcesField, WrappedTarget
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
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = (_DOCKERFILE_PACKAGE, "dockerfile.lock")
    default_lockfile_path = f"src/python/{_DOCKERFILE_PACKAGE.replace('.', '/')}/dockerfile.lock"
    default_lockfile_url = git_url(default_lockfile_path)


class DockerfileParserLockfileSentinel(GenerateToolLockfileSentinel):
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
    parser_script_content = pkgutil.get_data(_DOCKERFILE_PACKAGE, _DOCKERFILE_SANDBOX_TOOL)
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
    source: str
    from_image_addresses: tuple[str, ...] = ()
    copy_source_paths: tuple[str, ...] = ()
    version_tags: tuple[str, ...] = ()
    build_args: DockerBuildArgs = DockerBuildArgs()
    from_image_build_arg_names: tuple[str, ...] = ()
    copy_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class DockerfileInfoRequest:
    address: Address


def split_iterable(sep: str, obj: list[str] | tuple[str, ...]) -> Iterator[tuple[str, ...]]:
    while sep in obj:
        idx = obj.index(sep)
        yield tuple(obj[:idx])
        obj = obj[idx + 1 :]
    yield tuple(obj)


@rule
async def parse_dockerfile(request: DockerfileInfoRequest) -> DockerfileInfo:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target
    sources = await Get(
        HydratedSources,
        HydrateSourcesRequest(
            target.get(SourcesField),
            for_sources_types=(DockerImageSourceField,),
            enable_codegen=True,
        ),
    )

    dockerfile = sources.snapshot.files[0]

    result = await Get(
        ProcessResult,
        DockerfileParseRequest(
            sources.snapshot.digest,
            (
                "version-tags,from-image-addresses,copy-source-paths,build-args,from-image-build-args,copy-sources",
                dockerfile,
            ),
        ),
    )

    output = result.stdout.decode("utf-8").strip().split("\n")
    (
        version_tags,
        from_image_addresses,
        copy_source_paths,
        build_args,
        from_image_build_arg_names,
        copy_sources,
    ) = split_iterable("---", output)

    try:
        return DockerfileInfo(
            address=request.address,
            digest=sources.snapshot.digest,
            source=dockerfile,
            from_image_addresses=from_image_addresses,
            copy_source_paths=copy_source_paths,
            version_tags=version_tags,
            build_args=DockerBuildArgs.from_strings(*build_args, duplicates_must_match=True),
            from_image_build_arg_names=from_image_build_arg_names,
            copy_sources=copy_sources,
        )
    except ValueError as e:
        raise DockerfileInfoError(
            f"Error while parsing {dockerfile} for the {request.address} target: {e}"
        ) from e


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        *pex.rules(),
        UnionRule(GenerateToolLockfileSentinel, DockerfileParserLockfileSentinel),
    )
