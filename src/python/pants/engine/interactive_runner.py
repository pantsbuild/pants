# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pants.util.collections import Enum
from subprocess import Popen
from pants.engine.rules import RootRule
from tempfile import TemporaryDirectory
from typing import Any, Dict, Tuple
from pants.base.exception_sink import ExceptionSink


@dataclass(frozen=True)
class InteractiveProcessResult:
  process_exit_code: int


@dataclass(frozen=True)
class InteractiveProcessRequest:
  argv: Tuple[str, ...]
  env: Tuple[str, ...] = ()
  run_in_workspace: bool = False


@dataclass(frozen=True)
class InteractiveRunner:
  _scheduler: Any

  def run_local_interactive_process(self, request: InteractiveProcessRequest) -> InteractiveProcessResult:
    ExceptionSink.toggle_ignoring_sigint_v2_engine(True)
    return self._scheduler.run_local_interactive_process(request)


def create_interactive_runner_rules():
  return [RootRule(InteractiveRunner)]
