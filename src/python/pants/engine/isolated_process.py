# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ExecuteProcessRequest(datatype(['argv', 'env', 'input_files_digest', 'digest_length', 'output_files'])):
  """Request for execution with args and snapshots to extract."""

  @classmethod
  def create_from_snapshot(cls, argv, env, snapshot, output_files):
    return ExecuteProcessRequest(
      argv=argv,
      env=env,
      input_files_digest=snapshot.fingerprint,
      digest_length=snapshot.digest_length,
      output_files=output_files,
    )

  @classmethod
  def create_with_empty_snapshot(cls, argv, env, output_files):
    return cls.create_from_snapshot(argv, env, EMPTY_SNAPSHOT, output_files)

  def __new__(cls, argv, env, input_files_digest, digest_length, output_files):
    """

    :param args: Arguments to the process being run.
    :param env: A tuple of environment variables and values.
    """
    if not isinstance(argv, tuple):
      raise ValueError('argv must be a tuple.')

    if not isinstance(env, tuple):
      raise ValueError('env must be a tuple.')

    if not isinstance(input_files_digest, str):
      raise ValueError('input_files_digest must be a str.')

    if not isinstance(digest_length, int):
      raise ValueError('digest_length must be an int.')
    if digest_length < 0:
      raise ValueError('digest_length must be >= 0.')

    if not isinstance(output_files, tuple):
      raise ValueError('output_files must be a tuple.')

    return super(ExecuteProcessRequest, cls).__new__(cls, argv, env, input_files_digest, digest_length, output_files)


class ExecuteProcessResult(datatype(['stdout', 'stderr', 'exit_code', 'snapshot'])):
  pass


def create_process_rules():
  """Intrinsically replaced on the rust side."""
  return [execute_process_noop, RootRule(ExecuteProcessRequest)]


@rule(ExecuteProcessResult, [Select(ExecuteProcessRequest)])
def execute_process_noop(*args):
  raise Exception('This task is replaced intrinsically, and should never run.')
