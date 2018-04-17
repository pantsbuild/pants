# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractproperty
from binascii import hexlify

from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.rules import RootRule, SingletonRule, rule
from pants.engine.selectors import Select
from pants.util.contextutil import open_tar, temporary_dir
from pants.util.dirutil import safe_mkdir
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class Binary(object):
  """Binary in the product graph.

  TODO(cosmicexplorer): this should probably be coupled with instances of
  BinaryTool subclasses.
  """

  @abstractproperty
  def bin_path(self):
    pass


class ExecuteProcessRequest(datatype('ExecuteProcessRequest', ['argv', 'env', 'input_files_digest', 'digest_length'])):
  """Request for execution with args and snapshots to extract."""

  @classmethod
  def create_from_snapshot(cls, argv, env, snapshot):
    return ExecuteProcessRequest(
      argv=argv,
      env=env,
      input_files_digest=snapshot.fingerprint,
      digest_length=snapshot.digest_length,
    )

  @classmethod
  def create_with_empty_snapshot(cls, argv, env):
    return cls.create_from_snapshot(argv, env, EMPTY_SNAPSHOT)

  def __new__(cls, argv, env, input_files_digest, digest_length):
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

    return super(ExecuteProcessRequest, cls).__new__(cls, argv, env, input_files_digest, digest_length)


class ExecuteProcessResult(datatype('ExecuteProcessResult', ['stdout', 'stderr', 'exit_code'])):
  pass


def create_process_rules():
  """Intrinsically replaced on the rust side."""
  return [execute_process_noop, RootRule(ExecuteProcessRequest)]


@rule(ExecuteProcessResult, [Select(ExecuteProcessRequest)])
def execute_process_noop(*args):
  raise Exception('This task is replaced intrinsically, and should never run.')
