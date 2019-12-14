# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.jvm.subsystems.scalafmt import ScalaFmtSubsystem
from pants.binaries.binary_tool import BinaryToolFetchRequest
from pants.engine.console import Console
from pants.engine.fs import Snapshot
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.rules import console_rule, optionable_rule, rule


@dataclass(frozen=True)
class SingleFile:
  snapshot: Snapshot


@dataclass(frozen=True)
class FileCollection:
  snapshot: Snapshot


@dataclass(frozen=True)
class ScalaFmtNativeImage:
  exe: SingleFile


@dataclass(frozen=True)
class ScalaFmtRequest:
  config_file: SingleFile
  input_files: FileCollection
  scalafmt_tool: ScalaFmtNativeImage


@dataclass(frozen=True)
class ScalaFmtExeRequest:
  exe_req: ExecuteProcessRequest


@rule
def make_scalafmt_exe_req(req: ScalaFmtRequest, scalafmt: ScalaFmtSubsystem) -> ScalaFmtExeRequest:
  



class ScalaFmt(Goal):
  """???"""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--???')


@console_rule
def scalafmt_v2(console: Console) -> ScalaFmt:
  return ScalaFmt(exit_code=0)


def rules():
  return [
    optionable_rule(ScalaFmtSubsystem),
    scalafmt_v2,
  ]
