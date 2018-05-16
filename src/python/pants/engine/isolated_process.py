# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.engine.fs import EMPTY_SNAPSHOT, DirectoryDigest
from pants.util.objects import TypeCheckError, datatype


logger = logging.getLogger(__name__)


class ExecuteProcessRequest(datatype([('argv', tuple), ('env', tuple), ('input_files', DirectoryDigest)])):
  """Request for execution with args and snapshots to extract."""

  @classmethod
  def create_from_snapshot(cls, argv, env, snapshot):
    cls._verify_env_is_dict(env)
    return ExecuteProcessRequest(
      argv=argv,
      env=tuple(env.items()),
      input_files=snapshot.directory_digest,
    )

  @classmethod
  def create_with_empty_snapshot(cls, argv, env):
    return cls.create_from_snapshot(argv, env, EMPTY_SNAPSHOT)

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


class ExecuteProcessResult(datatype(['stdout', 'stderr', 'exit_code'])):
  pass
