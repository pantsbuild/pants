# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from itertools import chain
from typing import Iterator

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


_address_regexp = re.compile(
    r"""
    (?://)?[^:# ]*:[^:#!@?/\= ]+(?:\#[^:#!@?= ]+)?$
    """,
    re.VERBOSE,
)


def valid_address(value: str) -> bool:
    """Checks if `value` may pass as an address."""
    return bool(re.match(_address_regexp, value))


_image_ref_regexp = re.compile(
    r"""
    ^
    # Optional registry.
    ((?P<registry>[^/:_ ]+:?[^/:_ ]*)/)?
    # Repository.
    (?P<repository>[^:@ \t\n\r\f\v]+)
    # Optionally with `:tag`.
    (:(?P<tag>[^@ ]+))?
    # Optionally with `@digest`.
    (@(?P<digest>\S+))?
    $
    """,
    re.VERBOSE,
)


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

        def get_all(self, command_name: str) -> Iterator[Command]:
            for command in self.commands:
                if command.cmd.upper() == command_name:
                    yield command

        def copy_source_addresses(self) -> Iterator[str]:
            for copy in self.get_all("COPY"):
                if copy.flags:
                    # Do not consider COPY --from=... instructions etc.
                    continue
                # The last element of copy.value is the destination.
                for source in copy.value[:-1]:
                    address = translate_to_address(source)
                    if address:
                        yield address

        def from_image_addresses(self) -> Iterator[str]:
            build_args = {
                key: value
                for key, has_value, value in [
                    build_arg.partition("=") for build_arg in self.build_args()
                ]
                if has_value and valid_address(value)
            }

            for image_build_arg in self.from_image_build_args():
                if image_build_arg in build_args:
                    yield build_args[image_build_arg]

        def putative_target_addresses(self) -> tuple[str, ...]:
            addresses: list[str] = []
            addresses.extend(self.copy_source_addresses())
            addresses.extend(self.from_image_addresses())
            return tuple(addresses)

        def from_baseimages(self) -> Iterator[tuple[str, tuple[str, ...]]]:
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

            def _get_tag(image_ref: str) -> str | None:
                """The image ref is in the form `registry/repo/name[/...][:tag][@digest]` and where
                `digest` is `sha256:hex value`."""
                parsed = re.match(_image_ref_regexp, image_ref)
                if not parsed:
                    return None
                tag = parsed.group("tag")
                if tag:
                    return tag
                if not parsed.group("digest"):
                    return "latest"
                return None

            return tuple(
                f"{stage} {tag}"
                for stage, name_parts in self.from_baseimages()
                for tag in [_get_tag(name_parts[-1])]
                if tag
            )

        def build_args(self) -> tuple[str, ...]:
            """Return all defined build args, including any default values."""
            return tuple(cmd.original[4:].strip() for cmd in self.get_all("ARG"))

        def from_image_build_args(self) -> Iterator[str]:
            """Return build args used as the image ref in `FROM` instructions.

            Example:

                ARG BASE_IMAGE
                FROM ${BASE_IMAGE}
            """
            for cmd in self.get_all("FROM"):
                image_ref = cmd.value[0]
                build_arg = re.match(r"\$\{?([a-zA-Z0-9_]+)\}?$", image_ref)
                if build_arg:
                    yield build_arg.group(1)

        def copy_source_references(self) -> tuple[str, ...]:
            """Return all files referenced from the build context using COPY instruction."""
            return tuple(chain(*(cmd.value[:-1] for cmd in self.get_all("COPY"))))

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
        elif cmd == "from-image-build-args":
            for build_arg in parsed.from_image_build_args():
                print(build_arg)
        elif cmd == "copy-sources":
            for src in parsed.copy_source_references():
                print(src)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        for idx, cmd in enumerate(sys.argv[1].split(",")):
            if idx:
                print("---")
            main(cmd.strip(), sys.argv[2:])
    else:
        print(f"Not enough arguments.\nUsage: {sys.argv[0]} [COMMAND,COMMAND,...] [DOCKERFILE ...]")
        sys.exit(1)
