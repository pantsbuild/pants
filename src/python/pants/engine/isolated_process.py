# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from future.utils import binary_type, text_type

from pants.engine.fs import DirectoryDigest
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.objects import DatatypeFieldDecl as F
from pants.util.objects import Exactly, TypeCheckError, datatype


logger = logging.getLogger(__name__)

_default_timeout_seconds = 15 * 60


class ExecuteProcessRequest(datatype([
  ('argv', tuple),
  ('input_files', DirectoryDigest),
  ('description', text_type),
  # TODO: allow inferring a default value if a type is provided which has a 0-arg constructor.
  F('env', Exactly(tuple, dict, type(None)), default_value=None),
  F('output_files', tuple, default_value=()),
  F('output_directories', tuple, default_value=()),
  # NB: timeout_seconds covers the whole remote operation including queuing and setup.
  F('timeout_seconds', Exactly(float, int), default_value=_default_timeout_seconds),
  F('jdk_home', Exactly(text_type, type(None)), default_value=None),
])):
  """Request for execution with args and snapshots to extract."""

  def __new__(cls, *args, **kwargs):
    this_object = super(ExecuteProcessRequest, cls).__new__(cls, *args, **kwargs)

    env = this_object.env
    # `env` is a tuple, a dict, or None.
    if env is None:
      env = ()
    elif isinstance(env, tuple):
      pass
    else:
      if not isinstance(env, dict):
        raise TypeCheckError(
          cls.__name__,
          "arg 'env' was invalid: value {} (with type {}) must be a dict".format(
            env,
            type(env)
          )
        )
      env = tuple(item for pair in env.items() for item in pair)

    return this_object.copy(env=env)


class ExecuteProcessResult(datatype([('stdout', binary_type),
                                     ('stderr', binary_type),
                                     ('output_directory_digest', DirectoryDigest)
                                     ])):
  """Result of successfully executing a process.

  Requesting one of these will raise an exception if the exit code is non-zero."""


class FallibleExecuteProcessResult(datatype([('stdout', binary_type),
                                             ('stderr', binary_type),
                                             ('exit_code', int),
                                             ('output_directory_digest', DirectoryDigest)
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
      desc=process_description, code=exit_code, stdout=stdout, stderr=stderr)

    super(ProcessExecutionFailure, self).__init__(msg)


@rule(ExecuteProcessResult, [Select(FallibleExecuteProcessResult), Select(ExecuteProcessRequest)])
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
