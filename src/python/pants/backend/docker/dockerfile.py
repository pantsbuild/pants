# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass, fields
from typing import Collection, Generator, Tuple

from pants.backend.docker.dockerfile_commands import DockerfileCommand
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass
class Dockerfile:
    commands: Tuple[DockerfileCommand, ...]

    def __init__(self, commands: Collection[DockerfileCommand]) -> None:
        super().__init__()
        self.commands = tuple(commands)

    @classmethod
    def parse(cls, dockerfile_source: str) -> "Dockerfile":
        commands = []
        for command_line in cls._iter_command_lines(dockerfile_source):
            cmd = DockerfileCommand.decode(command_line)
            if cmd:
                commands.append(cmd)

        return Dockerfile(commands)

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
