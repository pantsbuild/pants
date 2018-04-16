# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
import os
from abc import abstractproperty
from binascii import hexlify

from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.rules import RootRule, SingletonRule, TaskRule, rule
from pants.engine.selectors import Select
from pants.util.contextutil import open_tar, temporary_dir
from pants.util.dirutil import safe_mkdir
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


def _run_command(binary, sandbox_dir, process_request):
  command = binary.prefix_of_command() + tuple(process_request.args)
  logger.debug('Running command: "{}" in {}'.format(command, sandbox_dir))
  popen = subprocess.Popen(command,
                           stderr=subprocess.PIPE,
                           stdout=subprocess.PIPE,
                           cwd=sandbox_dir)
  # TODO: At some point, we may want to replace this blocking wait with a timed one that returns
  # some kind of in progress state.
  popen.wait()
  logger.debug('Done running command in {}'.format(sandbox_dir))
  return popen


def _snapshot_path(snapshot, archive_root):
  """TODO: This is an abstraction leak... see _Snapshots."""
  fingerprint_hex = hexlify(snapshot.fingerprint)
  snapshot_dir = os.path.join(archive_root, fingerprint_hex[0:2], fingerprint_hex[2:4])
  safe_mkdir(snapshot_dir)
  return os.path.join(snapshot_dir, '{}.tar'.format(fingerprint_hex))


def _extract_snapshot(snapshot_archive_root, snapshot, sandbox_dir):
  with open_tar(_snapshot_path(snapshot, snapshot_archive_root), errorlevel=1) as tar:
    tar.extractall(sandbox_dir)


def _snapshotted_process(input_conversion,
                         output_conversion,
                         snapshot_directory,
                         binary,
                         *args):
  """A pickleable top-level function to execute a process.

  Receives two conversion functions, some required inputs, and the user-declared inputs.
  """
  process_request = input_conversion(*args)

  # TODO resolve what to do with output files, then make these tmp dirs cleaned up.
  with temporary_dir(cleanup=False) as sandbox_dir:
    if process_request.snapshots:
      for snapshot in process_request.snapshots:
        _extract_snapshot(snapshot_directory.root, snapshot, sandbox_dir)

    # All of the snapshots have been checked out now.
    if process_request.directories_to_create:
      for d in process_request.directories_to_create:
        safe_mkdir(os.path.join(sandbox_dir, d))

    popen = _run_command(binary, sandbox_dir, process_request)

    process_result = SnapshottedProcessResult(popen.stdout.read(), popen.stderr.read(), popen.returncode)
    if process_result.exit_code != 0:
      raise Exception('Running {} failed with non-zero exit code: {}'.format(binary,
                                                                             process_result.exit_code))

    return output_conversion(process_result, sandbox_dir)


def _setup_process_execution(input_conversion, *args):
  """A pickleable top-level function to setup pre-execution.
  """
  return input_conversion(*args)


def _post_process_execution(output_conversion, *args):
  """A pickleable top-level function to execute a process.

  Receives two conversion functions, some required inputs, and the user-declared inputs.
  """
  return output_conversion(*args)


class Binary(object):
  """Binary in the product graph.

  TODO(cosmicexplorer): this should probably be coupled with instances of
  BinaryTool subclasses.
  """

  @abstractproperty
  def bin_path(self):
    pass


class SnapshottedProcessRequest(datatype('SnapshottedProcessRequest',
                                         ['args', 'snapshots', 'directories_to_create'])):
  """Request for execution with binary args and snapshots to extract."""

  def __new__(cls, args, snapshots=tuple(), directories_to_create=tuple(), **kwargs):
    """

    :param args: Arguments to the binary being run.
    :param snapshot_subjects: Subjects used to request snapshots that will be checked out into the sandbox.
    :param directories_to_create: Directories to ensure exist in the sandbox before execution.
    """
    if not isinstance(args, tuple):
      raise ValueError('args must be a tuple.')
    if not isinstance(snapshots, tuple):
      raise ValueError('snapshots must be a tuple.')
    if not isinstance(directories_to_create, tuple):
      raise ValueError('directories_to_create must be a tuple.')
    return super(SnapshottedProcessRequest, cls).__new__(cls, args, snapshots, directories_to_create, **kwargs)


class SnapshottedProcessResult(datatype('SnapshottedProcessResult', ['stdout', 'stderr', 'exit_code'])):
  """Contains the stdout, stderr and exit code from executing a process."""


class _Snapshots(datatype('_Snapshots', ['root'])):
  """Private singleton value to expose the snapshot directory (managed by rust) to python.

  TODO: This is an abstraction leak, but it's convenient to be able to pipeline the input/output
  conversion tasks into a single Task node.
  """

def create_snapshot_rules():
  """Intrinsically replaced on the rust side."""
  return [
      SingletonRule(_Snapshots, _Snapshots('/dev/null'))
    ]


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

    if isinstance(input_files_digest, unicode):
      input_files_digest = str(input_files_digest)

    if not isinstance(input_files_digest, str):
      raise ValueError('input_files_digest must be a str or unicode.')

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
