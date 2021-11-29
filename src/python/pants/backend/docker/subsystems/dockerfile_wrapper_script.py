# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Generator

#
# Note: This file is used as an pex entry point in the execution sandbox.
#


_pex_target_regexp = re.compile(
    r"""
    (?# optional path, one level with dot-separated parts)
    (?:(?P<path>(?:\w[.0-9_-]?)+) /)?

    (?# binary name, with .pex file extension)
    (?P<name>(?:\w[.0-9_-]?)+) \.pex$
    """,
    re.VERBOSE,
)


def translate_to_address(value: str) -> str | None:
    # Translate something that resembles a packaged pex binary to its corresponding target
    # address. E.g. src.python.tool/bin.pex => src/python/tool:bin
    pex = re.match(_pex_target_regexp, value)
    if pex:
        path = (pex.group("path") or "").replace(".", "/")
        name = pex.group("name")
        return ":".join([path, name])

    return None


def main(cmd: str, args: list[str]) -> None:
    # import here to allow the rest of the file to be tested without a dependency on dockerfile
    from dockerfile import Command, parse_file, parse_string

    @dataclass(frozen=True)
    class ParsedDockerfile:
        commands: tuple[Command, ...]

        @classmethod
        def from_file(cls, dockerfile: str) -> ParsedDockerfile:
            return cls(parse_file(dockerfile))

        @classmethod
        def from_string(cls, dockerfile_contents: str) -> ParsedDockerfile:
            return cls(parse_string(dockerfile_contents))

        def get_all(self, command_name: str) -> Generator[Command, None, None]:
            for command in self.commands:
                if command.cmd.upper() == command_name:
                    yield command

        def copy_source_addresses(self) -> Generator[str, None, None]:
            for copy in self.get_all("COPY"):
                if copy.flags:
                    # Do not consider COPY --from=... instructions etc.
                    continue
                # The last element of copy.value is the destination.
                for source in copy.value[:-1]:
                    address = translate_to_address(source)
                    if address:
                        yield address

        def putative_target_addresses(self) -> tuple[str, ...]:
            addresses: list[str] = []
            addresses.extend(self.copy_source_addresses())
            return tuple(addresses)

        def from_baseimages(self) -> Generator[tuple[str, tuple[str, ...]], None, None]:
            for idx, cmd in enumerate(self.get_all("FROM")):
                name_parts = cmd.value[0].split("/")
                if len(cmd.value) == 3 and cmd.value[1].upper() == "AS":
                    stage = cmd.value[2]
                else:
                    stage = f"stage{idx}"
                yield stage, name_parts

        def baseimage_tags(self) -> tuple[str, ...]:
            """Return all base image tags, prefix with the stage alias or index.

            Example:

                FROM base:1.0 AS build
                ...
                FROM interim
                ...
                FROM final as out

            Gives:

                build 1.0
                stage1 latest
                out latest
            """
            return tuple(
                " ".join(
                    [
                        stage,
                        name_parts[-1].rsplit(":", maxsplit=1)[-1]
                        if ":" in name_parts[-1]
                        else "latest",
                    ]
                )
                for stage, name_parts in self.from_baseimages()
            )

        def build_args(self) -> tuple[str, ...]:
            """Return all defined build args, including any default values."""
            return tuple(cmd.original[4:].strip() for cmd in self.get_all("ARG"))

    for parsed in map(ParsedDockerfile.from_file, args):
        if cmd == "putative-targets":
            for addr in parsed.putative_target_addresses():
                print(addr)
        elif cmd == "version-tags":
            for tag in parsed.baseimage_tags():
                print(tag)
        elif cmd == "build-args":
            for arg in parsed.build_args():
                print(arg)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        for idx, cmd in enumerate(sys.argv[1].split(",")):
            if idx:
                print("---")
            main(cmd.strip(), sys.argv[2:])
    else:
        print(f"Not enough arguments.\nUsage: {sys.argv[0]} [COMMAND,COMMAND,...] [DOCKERFILE ...]")
        sys.exit(1)
