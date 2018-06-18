# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

import six

from pants.engine.fs import EMPTY_SNAPSHOT, DirectoryDigest
from pants.engine.rules import RootRule
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
    env,
    snapshot,
    output_files=(),
    output_directories=(),
    timeout_seconds=_default_timeout_seconds,
    description='process'
  ):
    cls._verify_env_is_dict(env)
    return ExecuteProcessRequest(
      argv=argv,
      env=tuple(env.items()),
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
    env,
    output_files=(),
    output_directories=(),
    timeout_seconds=_default_timeout_seconds,
    description='process'
  ):
    return cls.create_from_snapshot(
      argv,
      env,
      EMPTY_SNAPSHOT,
      output_files,
      output_directories,
      timeout_seconds,
      description
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


class ExecuteProcessResult(datatype(['stdout', 'stderr', 'exit_code', 'output_directory_digest'])):
  pass


def create_process_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(ExecuteProcessRequest),
  ]
