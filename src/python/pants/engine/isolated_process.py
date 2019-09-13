# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.engine.fs import Digest
from pants.engine.platform import PlatformConstraint
from pants.engine.rules import RootRule, rule
from pants.util.objects import (Exactly, TypedCollection, datatype, hashable_string_list,
                                string_optional)


logger = logging.getLogger(__name__)

_default_timeout_seconds = 15 * 60


class ProductDescription(datatype([('value', str)])): pass


class ExecuteProcessRequest(datatype([
  ('argv', hashable_string_list),
  ('input_files', Digest),
  ('description', str),
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

    return super().__new__(
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


class MultiPlatformExecuteProcessRequest(datatype([
  ('platform_constraints', hashable_string_list),
  ('execute_process_requests', TypedCollection(Exactly(ExecuteProcessRequest))),
])):
  # args collects a set of tuples representing platform constraints mapped to a req, just like a dict constructor can.

  def __new__(cls, request_dict):
    if len(request_dict) == 0:
      raise cls.make_type_error("At least one platform constrained ExecuteProcessRequest must be passed.")

    # validate the platform constraints using the platforms enum an flatten the keys.
    validated_constraints = tuple(
      constraint.value
      for pair in request_dict.keys() for constraint in pair
      if PlatformConstraint(constraint.value)
    )
    if len({req.description for req in request_dict.values()}) != 1:
      raise ValueError(f"The `description` of all execute_process_requests in a {cls.__name__} must be identical.")

    return super().__new__(
      cls,
      validated_constraints,
      tuple(request_dict.values())
    )

  @property
  def product_description(self):
    # we can safely extract the first description because we guarantee that at
    # least one request exists and that all of their descriptions are the same
    # in __new__
    return ProductDescription(self.execute_process_requests[0].description)


class ExecuteProcessResult(datatype([('stdout', bytes),
                                     ('stderr', bytes),
                                     ('output_directory_digest', Digest)
                                     ])):
  """Result of successfully executing a process.

  Requesting one of these will raise an exception if the exit code is non-zero."""


class FallibleExecuteProcessResult(datatype([('stdout', bytes),
                                             ('stderr', bytes),
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
      stdout=stdout.decode(),
      stderr=stderr.decode()
    )

    super().__init__(msg)


@rule(ProductDescription, [MultiPlatformExecuteProcessRequest])
def get_multi_platform_request_description(req):
  return req.product_description


@rule(MultiPlatformExecuteProcessRequest, [ExecuteProcessRequest])
def upcast_execute_process_request(req):
  """This rule allows an ExecuteProcessRequest to be run as a
  platform compatible MultiPlatformExecuteProcessRequest.
  """
  return MultiPlatformExecuteProcessRequest(
    {(PlatformConstraint.none, PlatformConstraint.none): req}
  )


@rule(ExecuteProcessResult, [FallibleExecuteProcessResult, ProductDescription])
def fallible_to_exec_result_or_raise(fallible_result, description):
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
      description.value
    )


def create_process_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(ExecuteProcessRequest),
    RootRule(MultiPlatformExecuteProcessRequest),
    upcast_execute_process_request,
    fallible_to_exec_result_or_raise,
    get_multi_platform_request_description,
  ]
