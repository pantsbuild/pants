# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Generator

from dockerfile import Command, parse_string

from pants.backend.docker.target_types import DockerImageSources
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.rules import Get, collect_rules, rule
from pants.option.global_options import GlobalOptions


@dataclass(frozen=True)
class DockerfileParseRequest:
    sources: DockerImageSources


@dataclass(frozen=True)
class DockerfileInfo:
    putative_target_addresses: tuple[str, ...] = ()


_pex_target_regexp = re.compile(
    r"""
    (?# optional path, one level with dot-separated parts)
    (?:(?P<path>(?:\w[.0-9_-]?)+) /)?

    (?# binary name, with .pex file extension)
    (?P<name>(?:\w[.0-9_-]?)+) \.pex$
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedDockerfile:
    commands: tuple[Command, ...]

    @classmethod
    def parse(cls, dockerfile_contents: str) -> "ParsedDockerfile":
        return cls(parse_string(dockerfile_contents))

    def get_all(self, command_name: str) -> Generator[Command, None, None]:
        for command in self.commands:
            if command.cmd.upper() == command_name:
                yield command

    @staticmethod
    def translate_to_address(value: str) -> str | None:
        # Translate something that resembles a packaged pex binary to its corresponding target
        # address. E.g. src.python.tool/bin.pex => src/python/tool:bin
        pex = re.match(_pex_target_regexp, value)
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
                address = self.translate_to_address(source)
                if address:
                    yield address

    def putative_target_addresses(self) -> tuple[str, ...]:
        addresses: list[str] = []
        addresses.extend(self.copy_source_addresses())
        return tuple(addresses)


@rule
async def parse_dockerfile(
    request: DockerfileParseRequest, global_options: GlobalOptions
) -> DockerfileInfo:
    if not request.sources.value:
        return DockerfileInfo()

    contents = await Get(
        DigestContents,
        PathGlobs,
        request.sources.path_globs(global_options.options.files_not_found_behavior),
    )

    parsed = ParsedDockerfile.parse(contents[0].content.decode())

    return DockerfileInfo(
        putative_target_addresses=parsed.putative_target_addresses(),
    )


def rules():
    return collect_rules()
