# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass, fields
from typing import Any, Dict, Generator, Optional, Tuple

from pants.backend.docker.commands import BaseImage, Copy, DockerfileCommand, EntryPoint


@dataclass(frozen=True)
class Dockerfile:
    baseimage: Optional[BaseImage] = None
    entry_point: Optional[EntryPoint] = None
    copy: Tuple[Copy, ...] = tuple()

    @classmethod
    def parse(cls, dockerfile_source: str) -> "Dockerfile":
        attrs: Dict[str, Any] = {}
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
