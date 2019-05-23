# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from future.utils import binary_type

from pants.engine.fs import Digest
from pants.engine.rules import RootRule, rule
from pants.util.objects import Exactly, datatype, hashable_string_list, string_optional, string_type


logger = logging.getLogger(__name__)

_default_timeout_seconds = 15 * 60


class ExecuteProcessRequest(datatype([
  ('argv', hashable_string_list),
  ('input_files', Digest),
  ('description', string_type),
  ('env', hashable_string_list),
  ('output_files', hashable_string_list),
  ('output_directories', hashable_string_list),
  # NB: timeout_seconds covers the whole remote operation including queuing and setup.
  ('timeout_seconds', Exactly(float, int)),
  ('jdk_home', string_optional),
])):
  """Request for execution with args and snapshots to extract."""

  # TODO: add a method to hack together a `process_executor` invocation command line which
  # reproduces this process execution request to make debugging remote executions effortless!
  def __new__(
    cls,
    argv,
    input_files,
    description,
    env=None,
    output_files=(),
    output_directories=(),
    timeout_seconds=_default_timeout_seconds,
    jdk_home=None,
  ):
    if env is None:
      env = ()
    else:
      if not isinstance(env, dict):
        raise cls.make_type_error(
          "arg 'env' was invalid: value {} (with type {}) must be a dict".format(env, type(env)))
      env = tuple(item for pair in env.items() for item in pair)

    return super(ExecuteProcessRequest, cls).__new__(
      cls,
      argv=argv,
      env=env,
      input_files=input_files,
      description=description,
      output_files=output_files,
      output_directories=output_directories,
      timeout_seconds=timeout_seconds,
      jdk_home=jdk_home,
    )


class ExecuteProcessResult(datatype([('stdout', binary_type),
                                     ('stderr', binary_type),
                                     ('output_directory_digest', Digest)
                                     ])):
  """Result of successfully executing a process.

  Requesting one of these will raise an exception if the exit code is non-zero."""


class FallibleExecuteProcessResult(datatype([('stdout', binary_type),
                                             ('stderr', binary_type),
                                             ('exit_code', int),
                                             ('output_directory_digest', Digest)
                                             ])):
  """Result of executing a process.

  Requesting one of these will not raise an exception if the exit code is non-zero."""


class ProcessExecutionFailure(Exception):
  """Used to denote that a process exited, but was unsuccessful in some way.

  For example, exiting with a non-zero code.
  """

  MSG_FMT = """process '{desc}' failed with exit code {code}.
stdout:
{stdout}
stderr:
{stderr}
"""

  def __init__(self, exit_code, stdout, stderr, process_description):
    # These are intentionally "public" members.
    self.exit_code = exit_code
    self.stdout = stdout
    self.stderr = stderr

    msg = self.MSG_FMT.format(
      desc=process_description,
      code=exit_code,
      stdout=stdout.decode('utf-8'),
      stderr=stderr.decode('utf-8')
    )

    super(ProcessExecutionFailure, self).__init__(msg)


@rule(ExecuteProcessResult, [FallibleExecuteProcessResult, ExecuteProcessRequest])
def fallible_to_exec_result_or_raise(fallible_result, request):
  """Converts a FallibleExecuteProcessResult to a ExecuteProcessResult or raises an error."""

  if fallible_result.exit_code == 0:
    return ExecuteProcessResult(
      fallible_result.stdout,
      fallible_result.stderr,
      fallible_result.output_directory_digest
    )
  else:
    raise ProcessExecutionFailure(
      fallible_result.exit_code,
      fallible_result.stdout,
      fallible_result.stderr,
      request.description
    )


def create_process_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(ExecuteProcessRequest),
    fallible_to_exec_result_or_raise
  ]
