# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import Digest
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import strip_v2_chroot_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompiledClassfiles:
    """The outputs of a compilation contained in either zero or one JAR file.

    TODO: Rename this type to align with the guarantee about its content.
    """

    digest: Digest


class CompileResult(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEPENDENCY_FAILED = "dependency failed"


@dataclass(frozen=True)
class FallibleCompiledClassfiles(EngineAwareReturnType):
    description: str
    result: CompileResult
    output: CompiledClassfiles | None
    exit_code: int
    stdout: str | None = None
    stderr: str | None = None

    @classmethod
    def from_fallible_process_result(
        cls,
        description: str,
        process_result: FallibleProcessResult,
        output: CompiledClassfiles | None,
        *,
        strip_chroot_path: bool = False,
    ) -> FallibleCompiledClassfiles:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        exit_code = process_result.exit_code
        # TODO: Coursier renders this line on macOS.
        stderr = "\n".join(
            line
            for line in prep_output(process_result.stderr).splitlines()
            if line != "setrlimit to increase file descriptor limit failed, errno 22"
        )
        return cls(
            description=description,
            result=(CompileResult.SUCCEEDED if exit_code == 0 else CompileResult.FAILED),
            output=output,
            exit_code=exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=stderr,
        )

    def level(self) -> LogLevel:
        return LogLevel.ERROR if self.exit_code != 0 else LogLevel.INFO

    def message(self) -> str:
        message = self.description
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )
        if self.stdout:
            message += f"\n{self.stdout}"
        if self.stderr:
            message += f"\n{self.stderr}"
        return message

    def cacheable(self) -> bool:
        # Failed compile outputs should be re-rendered in every run.
        return self.exit_code == 0


@rule
def required_classfiles(fallible_result: FallibleCompiledClassfiles) -> CompiledClassfiles:
    if fallible_result.result == CompileResult.SUCCEEDED:
        assert fallible_result.output
        return fallible_result.output
    # NB: The compile outputs will already have been streamed as FallibleCompiledClassfiles finish.
    raise Exception(
        f"Compile failed:\nstdout:\n{fallible_result.stdout}\nstderr:\n{fallible_result.stderr}"
    )


def rules():
    return collect_rules()
