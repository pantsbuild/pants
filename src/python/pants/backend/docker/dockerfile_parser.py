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


def main(args):
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

    for parsed in map(ParsedDockerfile.from_file, args):
        for addr in parsed.putative_target_addresses():
            print(addr)


if __name__ == "__main__":
    main(sys.argv[1:])
