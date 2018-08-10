# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

import six

from pants.engine.fs import EMPTY_SNAPSHOT, DirectoryDigest
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.objects import Exactly, SubclassesOf, TypeCheckError, datatype


logger = logging.getLogger(__name__)

_default_timeout_seconds = 15 * 60


class ExecuteProcessRequest(datatype([
  ('argv', tuple),
  ('env', tuple),
  ('input_files', DirectoryDigest),
  ('output_files', tuple),
  ('output_directories', tuple),
  # NB: timeout_seconds covers the whole remote operation including queuing and setup.
  ('timeout_seconds', Exactly(float, int)),
  ('description', SubclassesOf(*six.string_types)),
])):
  """Request for execution with args and snapshots to extract."""

  @classmethod
  def create_from_snapshot(
    cls,
    argv,
    snapshot,
    description,
    env=None,
    output_files=(),
    output_directories=(),
    timeout_seconds=_default_timeout_seconds,
  ):
    if env is None:
      env = ()
    else:
      cls._verify_env_is_dict(env)
      env = tuple(item for pair in env.items() for item in pair)

    return ExecuteProcessRequest(
      argv=argv,
      env=env,
      input_files=snapshot.directory_digest,
      output_files=output_files,
      output_directories=output_directories,
      timeout_seconds=timeout_seconds,
      description=description,
    )

  @classmethod
  def create_with_empty_snapshot(
    cls,
    argv,
    description,
    env=None,
    output_files=(),
    output_directories=(),
    timeout_seconds=_default_timeout_seconds,
  ):
    return cls.create_from_snapshot(
      argv,
      EMPTY_SNAPSHOT,
      description,
      env,
      output_files,
      output_directories,
      timeout_seconds,
    )

  @classmethod
  def _verify_env_is_dict(cls, env):
    if not isinstance(env, dict):
      raise TypeCheckError(
        cls.__name__,
        "arg 'env' was invalid: value {} (with type {}) must be a dict".format(
          env,
          type(env)
        )
      )


class ExecuteProcessResult(datatype(['stdout', 'stderr', 'output_directory_digest'])):
  """Result of successfully executing a process.

  Requesting one of these will raise an exception if the exit code is non-zero."""


class FallibleExecuteProcessResult(datatype(['stdout', 'stderr', 'exit_code', 'output_directory_digest'])):
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
