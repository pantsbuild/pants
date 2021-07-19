# -*- mode: python -*-
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from enum import Enum

from typing import Any, Dict, Generator, Optional, Pattern, Tuple, Type, Union


class DockerfileError(Exception):
    pass


class InvalidDockerfileCommandArgument(DockerfileError):
    """Invalid syntax for the Dockerfile command."""


class DockerfileCommand(ABC):
    """Base class for dockerfile commands encoding/decoding."""

    _command = "<OVERRIDE ME>"

    def _append(self, attr: str, dockerfile_attrs: Dict[str, Any]) -> None:
        dockerfile_attrs[attr] = (*dockerfile_attrs.get(attr, tuple()), self)

    @classmethod
    def _command_class(cls, command: str) -> Optional[Type["DockerfileCommand"]]:
        for cmd_cls in cls.__subclasses__():
            if cmd_cls._command == command:
                return cmd_cls
        return None

    @classmethod
    def from_arg(cls, arg: str) -> "DockerfileCommand":
        return cls(**cls.decode_arg(arg))

    @classmethod
    def decode(cls, command_line: str) -> Optional["DockerfileCommand"]:
        """Parse a Dockerfile command."""
        cmd, _, arg = command_line.partition(" ")
        cmd_cls = cls._command_class(cmd)
        if cmd_cls:
            return cmd_cls.from_arg(arg)
        return None

    def encode(self) -> str:
        """Convert command to string representation for a Dockerfile."""
        return " ".join([self._command, *self.encode_arg()])

    @staticmethod
    def _decode_arg_regexp(regexp: Union[Pattern, str], arg: str) -> Dict[str, Optional[str]]:
        m = regexp.match(arg)
        if not m:
            raise InvalidDockerfileCommandArgument(arg)
        return m.groupdict()

    @classmethod
    @abstractmethod
    def decode_arg(cls, arg: str) -> Dict[str, Optional[str]]:
        """Parse command arguments."""

    @abstractmethod
    def encode_arg(self) -> Generator[str, None, None]:
        """Convert command arg to string(s)"""

    @abstractmethod
    def register(self, dockerfile_attrs: Dict[str, Any]) -> None:
        """Add this command to Dockerfile attrs."""


@dataclass(frozen=True)
class BaseImage(DockerfileCommand):
    """The FROM instruction initializes a new build stage and sets the Base Image for subsequent
    instructions.

        FROM [--platform=<platform>] <image> [AS <name>]
        FROM [--platform=<platform>] <image>[:<tag>] [AS <name>]
        FROM [--platform=<platform>] <image>[@<digest>] [AS <name>]

    https://docs.docker.com/engine/reference/builder/#from
    """

    _command = "FROM"

    image: str
    name: Optional[str] = None
    tag: Optional[str] = None
    digest: Optional[str] = None
    platform: Optional[str] = None
    registry: Optional[str] = None

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
        re.VERBOSE,
    )

    def register(self, dockerfile_attrs: Dict[str, Any]) -> None:
        dockerfile_attrs["baseimage"] = self

    def encode_arg(self) -> Generator[str, None, None]:
        if self.platform:
            yield f"--platform={self.platform}"

        image = self.image
        if self.registry:
            image = "/".join([self.registry, self.image])
        if self.digest:
            image += f"@{self.digest}"
        elif self.tag:
            image += f":{self.tag}"

        yield image

        if self.name:
            yield f"AS {self.name}"

    @classmethod
    def decode_arg(cls, arg: str) -> Dict[str, Optional[str]]:
        return cls._decode_arg_regexp(cls._arg_regexp, arg)


@dataclass(frozen=True)
class EntryPoint(DockerfileCommand):
    """An ENTRYPOINT allows you to configure a container that will run as an executable.

        ENTRYPOINT ["executable", "param1", "param2"]  # form: exec
        ENTRYPOINT command param1 param2               # form: shell

    https://docs.docker.com/engine/reference/builder/#entrypoint
    """

    _command = "ENTRYPOINT"

    class Form(Enum):
        EXEC = "exec"
        SHELL = "shell"

    executable: str
    arguments: Optional[Tuple[str, ...]] = None
    form: Form = Form.EXEC

    def register(self, dockerfile_attrs: Dict[str, Any]) -> None:
        dockerfile_attrs["entry_point"] = self

    def encode_arg(self) -> Generator[str, None, None]:
        if self.form is EntryPoint.Form.EXEC:
            yield json.dumps([self.executable, *(self.arguments or [])])
        else:
            yield self.executable
            if self.arguments:
                yield " ".join(self.arguments)

    @classmethod
    def decode_arg(cls, arg: str) -> Dict[str, Optional[str]]:
        if arg.startswith("["):
            form = EntryPoint.Form.EXEC
            cmd_line = json.loads(arg)
        else:
            form = EntryPoint.Form.SHELL
            cmd_line = arg.split(" ")
        return dict(executable=cmd_line[0], arguments=tuple(cmd_line[1:]), form=form)


@dataclass(frozen=True)
class Copy(DockerfileCommand):
    """The COPY instruction copies new files or directories from <src> and adds them to the
    filesystem of the container at the path <dest>.

        COPY [--chown=<user>:<group>] <src>... <dest>
        COPY [--chown=<user>:<group>] ["<src>",... "<dest>"]

        COPY --from=<name> ...

    https://docs.docker.com/engine/reference/builder/#copy
    """

    _command = "COPY"

    src: Tuple[str]
    dest: str
    chown: str = None
    copy_from: str = None

    _arg_regexp = re.compile(
        r"""
        ^
        # optional flags
        (?:
          (--chown=(?P<chown>\S+)\s+)
          |
          (--from=(?P<copy_from>\S+)\s+)
        )*

        # paths, will be post processed
        (?P<paths>.+)
        $
        """,
        re.VERBOSE,
    )

    def register(self, dockerfile_attrs: Dict[str, Any]) -> None:
        self._append("copy", dockerfile_attrs)

    def encode_arg(self) -> Generator[str, None, None]:
        if self.copy_from:
            yield f"--from={self.copy_from}"

        if self.chown:
            yield f"--chown={self.chown}"

        paths = [*self.src, self.dest]
        if any(" " in s for s in paths if s):
            yield json.dumps(paths)
        else:
            for path in paths:
                yield path

    @classmethod
    def decode_arg(cls, arg: str) -> Dict[str, Optional[str]]:
        args = cls._decode_arg_regexp(cls._arg_regexp, arg)
        paths_string = args.pop("paths") or ""
        if paths_string.startswith("["):
            paths = json.loads(paths_string)
        else:
            paths = paths_string.split()

        if len(paths) > 1:
            args["src"] = tuple(paths[:-1])
            args["dest"] = paths[-1]
        return args

    # "RUN": ,
    # "CMD": ,
    # "LABEL": ,
    # "EXPOSE": ,
    # "ENV": ,
    # "ADD": ,
    # "COPY": ,
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
    baseimage: BaseImage = None
    entry_point: EntryPoint = None
    copy: Tuple[Copy, ...] = None

    @classmethod
    def parse(cls, dockerfile_source: str) -> "Dockerfile":
        attrs = {}
        for command_line in cls._iter_command_lines(dockerfile_source):
            cmd = DockerfileCommand.decode(command_line)
            if cmd:
                cmd.register(attrs)

        return Dockerfile(**attrs)

    def compile(self) -> str:
        return "\n".join(self._encode_fields())

    def _encode_fields(self) -> Generator[str, None, None]:
        for fld in fields(self):
            value = getattr(self, fld.name)
            if value:
                if isinstance(value, tuple):
                    for v in value:
                        yield v.encode()
                else:
                    yield value.encode()

    @staticmethod
    def _iter_command_lines(dockerfile_source: str) -> Generator[str, None, None]:
        unwraped = re.sub(r"\\[\r\n]+", "", dockerfile_source)
        for m in re.finditer("^.*$", unwraped, flags=re.MULTILINE):
            line = m.group().strip()
            if line and not line.startswith("#"):
                yield re.sub(r" +", " ", re.sub(r"\t", " ", line))
