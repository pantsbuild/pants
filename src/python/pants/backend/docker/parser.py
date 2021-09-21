# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import re
from dataclasses import InitVar, dataclass, field
from typing import Generator, Pattern

from dockerfile import Command, parse_string

from pants.backend.docker.target_types import DockerImageSources
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs
from pants.engine.rules import Get, collect_rules, rule


@dataclass(frozen=True)
class DockerfileParseRequest:
    sources: DockerImageSources


@dataclass(frozen=True)
class DockerfileInfo:
    putative_target_addresses: tuple[str, ...] = ()


@dataclass
class DockerfileParser:
    dockerfile: InitVar[str]
    commands: tuple[Command, ...] = field(init=False)

    pex_target_regexp: str = r"""
    (?# optional path, one level with dot-separated words)
    (?:(?P<path>(?:\w[.0-9_-]?)+) /)?

    (?# binary name, with .pex file extension)
    (?P<name>(?:\w[.0-9_-]?)+) \.pex$
    """

    def __post_init__(self, dockerfile: str):
        self.commands = parse_string(dockerfile)
        self._compiled_pex_target_regexp = re.compile(self.pex_target_regexp, re.VERBOSE)

    def get_all(self, command_name: str) -> Generator[Command, None, None]:
        for command in self.commands:
            if command.cmd.upper() == command_name:
                yield command

    @staticmethod
    def translate_to_address(value: str, pex_target_regexp: Pattern) -> str | None:
        # Translate something that resembles a packaged pex binary to its corresponding target
        # address. E.g. src.python.tool/bin.pex => src/python/tool:bin
        pex = re.match(pex_target_regexp, value)
        if pex:
            path = (pex.group("path") or "").replace(".", "/")
            name = pex.group("name")
            return ":".join([path, name])

        return None

    def copy_source_addresses(self) -> Generator[str, None, None]:
        for copy in self.get_all("COPY"):
            if copy.flags:
                # Do not consider COPY --from=... instructions etc.
                continue
            # The last element of copy.value is the destination.
            for source in copy.value[:-1]:
                address = self.translate_to_address(source, self._compiled_pex_target_regexp)
                if address:
                    yield address

    def putative_target_addresses(self) -> tuple[str, ...]:
        addresses: list[str] = []
        addresses.extend(self.copy_source_addresses())
        return tuple(addresses)


@rule
async def parse_dockerfile(request: DockerfileParseRequest) -> DockerfileInfo:
    if not request.sources.value:
        return DockerfileInfo()

    contents = await Get(
        DigestContents,
        PathGlobs(
            [os.path.join(request.sources.address.spec_path, request.sources.value[0])],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{request.sources.address}'s `{request.sources.alias}` field",
        ),
    )

    parser = DockerfileParser(contents[0].content.decode())

    return DockerfileInfo(
        putative_target_addresses=parser.putative_target_addresses(),
    )


def rules():
    return collect_rules()
