# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.lint.python_lint_target import PythonLintTarget
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.structs import PythonTargetAdaptor, TargetAdaptor
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.rules.core.lint import LintResult


@dataclass(frozen=True)
class PylintTarget:
  target: TargetAdaptor


def generate_args(wrapped_target: PylintTarget, pylint: Pylint) -> Tuple[str, ...]:
  args = []
  if pylint.options.config is not None:
    args.append(f"--config={pylint.options.config}")
  args.extend(pylint.options.args)
  args.extend(sorted(wrapped_target.target.sources.snapshot.files))
  return tuple(args)


@rule(name="Lint using Pylint")
async def lint(
  wrapped_target: PylintTarget,
  pylint: Pylint,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
  if pylint.options.skip:
    return LintResult.noop()

  target = wrapped_target.target

  # NB: Pylint output depends upon which Python interpreter version it's run with. We ensure that
  # each target runs with its own interpreter constraints. See
  # http://pylint.pycqa.org/en/latest/faq.html#what-versions-of-python-is-pylint-supporting.
  interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
    adaptors=[target] if isinstance(target, PythonTargetAdaptor) else [],
    python_setup=python_setup
  )

  config_path: Optional[str] = pylint.options.config
  config_snapshot = await Get[Snapshot](
    PathGlobs(include=tuple([config_path] if config_path else []))
  )
  requirements_pex = await Get[Pex](
    CreatePex(
      output_filename="pylint.pex",
      requirements=PexRequirements(requirements=tuple(pylint.get_requirement_specs())),
      interpreter_constraints=interpreter_constraints,
      entry_point=pylint.get_entry_point(),
    )
  )

  merged_input_files = await Get[Digest](
    DirectoriesToMerge(
      directories=(
        target.sources.snapshot.directory_digest,
        requirements_pex.directory_digest,
        config_snapshot.directory_digest,
      )
    ),
  )
  request = requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path=f'./pylint.pex',
    pex_args=generate_args(wrapped_target, pylint),
    input_files=merged_input_files,
    description=f'Run Pylint for {target.address.reference()}',
  )
  result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, request)
  return LintResult.from_fallible_execute_process_result(result)


def rules():
  return [lint, subsystem_rule(Pylint), UnionRule(PythonLintTarget, PylintTarget)]
