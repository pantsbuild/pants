# -*- mode: python -*-
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
#from textwrap import dedent
from typing import Any, Dict, Generator, Pattern, Optional, Type, Union


class DockerfileError (Exception):
    pass


class InvalidDockerfileCommandArgument(DockerfileError):
    """Invalid syntax for the Dockerfile command"""


class DockerfileCommand(ABC):
    """Base class for dockerfile commands encoding/decoding."""
    command = "<OVERRIDE ME>"

    @classmethod
    def _command_class(cls, command: str) -> Optional[Type["DockerfileCommand"]]:
        for cmd_cls in cls.__subclasses__():
            if cmd_cls.command == command:
                return cmd_cls
        return None

    @classmethod
    def from_arg(cls, arg: str) -> "DockerfileCommand":
        return cls(**cls.decode_arg(arg))

    @classmethod
    def decode(cls, command_line: str) -> Optional["DockerfileCommand"]:
        """Parse a Dockerfile command"""
        cmd, _, arg = command_line.partition(" ")
        cmd_cls = cls._command_class(cmd)
        if cmd_cls:
            return cmd_cls.from_arg(arg)
        return None

    def encode(self) -> str:
        """Convert command to string representation for a Dockerfile."""
        return " ".join([self.command, *self.encode_arg()])

    @staticmethod
    def _decode_arg_regexp(regexp: Union[Pattern, str], arg: str) -> Dict[str, Optional[str]]:
        m = regexp.match(arg)
        if not m:
            raise InvalidDockerfileCommandArgument(arg)
        return m.groupdict()

    @classmethod
    @abstractmethod
    def decode_arg(cls, arg: str) -> Dict[str, Optional[str]]:
        """Parse command arguments"""

    @abstractmethod
    def encode_arg(self) -> Generator[str, None, None]:
        """Convert command arg to string(s)"""

    @abstractmethod
    def register(self, dockerfile_attrs: Dict[str, Any]) -> None:
        """Add this command to Dockerfile attrs."""


@dataclass(frozen=True)
class BaseImage(DockerfileCommand):
    """The FROM instruction initializes a new build stage and sets the Base Image
    for subsequent instructions.

        FROM [--platform=<platform>] <image> [AS <name>]
        FROM [--platform=<platform>] <image>[:<tag>] [AS <name>]
        FROM [--platform=<platform>] <image>[@<digest>] [AS <name>]

    https://docs.docker.com/engine/reference/builder/#from

    """
    image: str
    name: Optional[str] = None
    tag: Optional[str] = None
    digest: Optional[str] = None
    platform: Optional[str] = None
    registry: Optional[str] = None

    command = "FROM"
    _arg_regexp = re.compile(
        r"""
        ^
        # optional platform
        (--platform=(?P<platform>\S+)\s+)?

        # optional registry
        ((?P<registry>\S+:[^/]+)/)?

        # image
        (?P<image>[^:@ \t\n\r\f\v]+)(

          # optionally with :tag or @digest
          (:(?P<tag>\S+)) | (@(?P<digest>\S+))

        )?

        # optional name
        (\s+AS\s+(?P<name>\S+))?
        $
        """,
        re.VERBOSE
    )

    def register(self, dockerfile_attrs: Dict[str, Any]) -> None:
        dockerfile_attrs['baseimage'] = self

    def encode_arg(self) -> Generator[str, None, None]:
        if self.platform:
            yield f"--platform={self.platform}"
        yield self.image
        if self.digest:
            yield f"@{self.digest}"
        elif self.tag:
            yield f":{self.tag}"
        if self.name:
            yield f"AS {self.name}"

    @classmethod
    def decode_arg(cls, arg: str) -> Dict[str, Optional[str]]:
        return cls._decode_arg_regexp(cls._arg_regexp, arg)

    # "RUN": ,
    # "CMD": ,
    # "LABEL": ,
    # "EXPOSE": ,
    # "ENV": ,
    # "ADD": ,
    # "COPY": ,
    # "ENTRYPOINT": ,
    # "VOLUME": ,
    # "USER": ,
    # "WORKDIR": ,
    # "ARG": ,
    # "ONBUILD": ,
    # "STOPSIGNAL": ,
    # "HEALTHCHECK": ,
    # "SHELL": ,


@dataclass(frozen=True)
class Dockerfile:
    baseimage: BaseImage

    @classmethod
    def parse(cls, dockerfile_source: str) -> "Dockerfile":
        attrs = {}
        for command_line in cls._iter_command_lines(dockerfile_source):
            cmd = DockerfileCommand.decode(command_line)
            if cmd:
                cmd.register(attrs)

        return Dockerfile(**attrs)

    @staticmethod
    def _iter_command_lines(dockerfile_source: str) -> Generator[str, None, None]:
        unwraped = re.sub(r"\\[\r\n]+", "", dockerfile_source)
        for m in re.finditer("^.*$", unwraped, flags=re.MULTILINE):
            line = m.group().strip()
            if line and not line.startswith("#"):
                yield re.sub(r" +", " ", re.sub(r"\t", " ", line))
