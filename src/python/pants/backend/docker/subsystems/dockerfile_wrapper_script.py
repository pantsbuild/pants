# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from itertools import chain
from typing import Iterator

#
# Note: This file is used as a pex entry point in the execution sandbox.
#


@dataclass(frozen=True)
class ParsedDockerfileInfo:
    """Keep fields in sync with `dockerfile_parser.py:DockerfileInfo`."""

    source: str
    build_args: tuple[str, ...]  # "ARG_NAME=VALUE", ...
    copy_source_paths: tuple[str, ...]
    copy_build_args: tuple[str, ...]  # "ARG_NAME=UPSTREAM_TARGET_ADDRESS", ...
    from_image_build_args: tuple[str, ...]  # "ARG_NAME=UPSTREAM_TARGET_ADDRESS", ...
    version_tags: tuple[str, ...]  # "STAGE TAG", ...


_address_regexp = re.compile(
    r"""
    # Optionally root:ed.
    (?://)?
    # Optional path.
    [^:# ]*
    # Optional target name.
    (?::[^:#!@?/\= ]+)?
    # Optional generated name.
    (?:\#[^:#!@?= ]+)?
    # Optional parametrizations.
    (?:@
      # key=value
      [^=: ]+=[^,: ]*
      # Optional additional `,key=value`s
      (?:,[^=: ]+=[^,: ]*)*
    )?
    $
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


def main(*dockerfile_names: str) -> Iterator[ParsedDockerfileInfo]:
    # import here to allow the rest of the file to be tested without a dependency on dockerfile
    from dockerfile import Command, parse_file, parse_string  # pants: no-infer-dep

    @dataclass(frozen=True)
    class ParsedDockerfile:
        filename: str
        commands: tuple[Command, ...]

        @classmethod
        def from_file(cls, dockerfile: str) -> ParsedDockerfile:
            return cls(dockerfile, parse_file(dockerfile))

        @classmethod
        def from_string(cls, dockerfile_contents: str) -> ParsedDockerfile:
            return cls("<text>", parse_string(dockerfile_contents))

        def get_info(self) -> ParsedDockerfileInfo:
            return ParsedDockerfileInfo(
                source=self.filename,
                build_args=self.build_args(),
                copy_source_paths=self.copy_source_paths(),
                copy_build_args=self.copy_build_args(),
                from_image_build_args=self.from_image_build_args(),
                version_tags=self.baseimage_tags(),
            )

        def get_all(self, command_name: str) -> Iterator[Command]:
            for command in self.commands:
                if command.cmd.upper() == command_name:
                    yield command

        def args_with_addresses(self):
            build_args = {
                key: value.strip("\"'")
                for key, has_value, value in [
                    build_arg.partition("=") for build_arg in self.build_args()
                ]
                if has_value and valid_address(value)
            }
            return build_args

        def from_image_build_args(self) -> tuple[str, ...]:
            build_args = self.args_with_addresses()

            return tuple(
                f"{image_build_arg}={build_args[image_build_arg]}"
                for image_build_arg in self.from_image_build_arg_names()
                if image_build_arg in build_args
            )

        @staticmethod
        def _extract_ref_from_arg(image_ref: str) -> str | None:
            build_arg = re.match(r"\$\{?([a-zA-Z0-9_]+)\}?$", image_ref)
            return build_arg.group(1) if build_arg else None

        def from_image_build_arg_names(self) -> Iterator[str]:
            """Return build args used as the image ref in `FROM` instructions.

            Example:

                ARG BASE_IMAGE
                FROM ${BASE_IMAGE}
            """
            for cmd in self.get_all("FROM"):
                build_arg = self._extract_ref_from_arg(cmd.value[0])
                if build_arg:
                    yield build_arg

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

            In case the base image is entirely made up of a build arg, use that with a `build-arg:`
            prefix.

            Example:

                FROM base:1.0 AS build
                ...
                FROM interim
                FROM $argname as dynamic
                ...
                FROM final as out

            Gives:

                build 1.0
                stage1 latest
                dynamic build-arg:argname
                out latest
            """

            def _get_tag(image_ref: str) -> str | None:
                """The image ref is in the form `registry/repo/name[/...][:tag][@digest]` and where
                `digest` is `sha256:hex value`, or a build arg reference with $ARG."""
                if image_ref.startswith("$"):
                    build_arg = self._extract_ref_from_arg(image_ref)
                    if build_arg:
                        return f"build-arg:{build_arg}"
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

        def copy_source_paths(self) -> tuple[str, ...]:
            """Return all files referenced from the build context using COPY instruction."""
            # Exclude COPY --from instructions, as they don't refer to files from the build context.
            return tuple(
                chain(
                    *(
                        cmd.value[:-1]
                        for cmd in self.get_all("COPY")
                        if all("--from" not in flag for flag in cmd.flags)
                    )
                )
            )

        def copy_build_args(self) -> tuple[str]:
            build_args = self.args_with_addresses()

            copied_files = self.copy_source_paths()

            out = []
            for f in copied_files:
                argref = self._extract_ref_from_arg(f)
                if argref:
                    if argref in build_args:
                        a = f"{argref}={build_args[argref]}"
                        out.append(a)

            return tuple(out)

    for parsed in map(ParsedDockerfile.from_file, dockerfile_names):
        yield parsed.get_info()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps([asdict(info) for info in main(*sys.argv[1:])]))
    else:
        print(f"Not enough arguments.\nUsage: {sys.argv[0]} [DOCKERFILE ...]")
        sys.exit(1)
