# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass, field
from typing import Collection, Generator, List, Optional, Tuple, Type, TypeVar, Union, cast

from pants.backend.docker.parser.dockerfile_commands import BaseImage, DockerfileCommand
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init

T = TypeVar("T", bound=DockerfileCommand)


class NoValue:
    pass


NOVALUE = NoValue()


@dataclass(frozen=True)
class DockerfileStage:
    parent: "Dockerfile" = field(hash=False, repr=False)
    index: int


@frozen_after_init
@dataclass(unsafe_hash=True)
class Dockerfile:
    commands: Tuple[DockerfileCommand, ...]

    _stage_info: Optional[DockerfileStage] = None
    stages: Tuple["Dockerfile", ...] = field(init=False, compare=False)
    stage: FrozenDict[str, "Dockerfile"] = field(init=False, compare=False)

    def __init__(
        self, commands: Collection[DockerfileCommand], _stage_info: Optional[DockerfileStage] = None
    ) -> None:
        super().__init__()
        self.commands = tuple(commands)
        self.stage = FrozenDict()
        if _stage_info:
            self._stage_info = _stage_info
            self.stages = ()
        else:
            self._stage_info = None
            self.stages = tuple(self._iter_stages())

        self.stage = FrozenDict({cast(str, stage.stage_name): stage for stage in self.stages})

    @classmethod
    def parse(cls, dockerfile_source: str) -> "Dockerfile":
        commands = []
        for command_line in cls._iter_command_lines(dockerfile_source):
            cmd = DockerfileCommand.decode(command_line)
            if cmd:
                commands.append(cmd)

        return Dockerfile(commands)

    def compile(self) -> str:
        return "\n".join(cmd.encode() for cmd in self.commands)

    @staticmethod
    def _iter_command_lines(dockerfile_source: str) -> Generator[str, None, None]:
        unwraped = re.sub(r"\\[\r\n]+", "", dockerfile_source)
        for m in re.finditer("^.*$", unwraped, flags=re.MULTILINE):
            line = m.group().strip()
            if line and not line.startswith("#"):
                yield re.sub(r" +", " ", re.sub(r"\t", " ", line))

    def _create_stage(
        self, stage_index: int, commands: Collection[DockerfileCommand]
    ) -> "Dockerfile":
        return Dockerfile(commands, _stage_info=DockerfileStage(self, stage_index))

    def _iter_stages(self) -> Generator["Dockerfile", None, None]:
        command_stack: List[DockerfileCommand] = []
        stage_index = 0

        for cmd in self.commands:
            if cmd.alias == "FROM":
                if command_stack:
                    yield self._create_stage(stage_index, command_stack)
                    stage_index += 1

                command_stack = []
            command_stack.append(cmd)

        yield self._create_stage(stage_index, command_stack)

    def get(self, command_type: Type[T], default: Union[T, None, NoValue] = NOVALUE) -> Optional[T]:
        for cmd in self.commands:
            if isinstance(cmd, command_type):
                return cmd

        if isinstance(default, NoValue):
            raise KeyError(f"Dockerfile has no {command_type} command instruction.")
        return default

    def get_all(self, command_type: Type[T]) -> Tuple[T, ...]:
        return tuple(cmd for cmd in self.commands if isinstance(cmd, command_type))

    @property
    def parent(self) -> Optional["Dockerfile"]:
        if self._stage_info:
            return self._stage_info.parent
        return None

    @property
    def stage_index(self) -> Optional[int]:
        if self._stage_info:
            return self._stage_info.index
        return None

    @property
    def stage_name(self) -> Optional[str]:
        if self._stage_info:
            base = self.get(BaseImage, None)
            if base:
                return base.name or str(self.stage_index)
        return None
