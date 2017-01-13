# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
import os
import shutil
import subprocess
from abc import abstractproperty
from hashlib import sha1

from pants.engine.fs import Dirs, Files
from pants.engine.selectors import Select
from pants.util.contextutil import open_tar, temporary_dir, temporary_file_path
from pants.util.dirutil import safe_mkdir
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


def create_snapshot_archive(project_tree, snapshot_directory, file_list, dir_list):
  logger.debug('snapshotting files: {}'.format(file_list))

  # Constructs the snapshot tar in a temporary location, then fingerprints it and moves it to the final path.
  with temporary_file_path(cleanup=False) as tmp_path:
    with open_tar(tmp_path, mode='w') as tar:
      for f in file_list.dependencies:
        # TODO handle GitProjectTree. Using add this this will fail with a non-filesystem project tree.
        tar.add(os.path.join(project_tree.build_root, f.path), f.path)
      for d in dir_list.dependencies:
        tar.add(os.path.join(project_tree.build_root, d.path), d.path, recursive=False)
    snapshot = Snapshot(_fingerprint_files_in_tar(file_list, tmp_path), file_list + dir_list)
  tar_location = _snapshot_path(snapshot, snapshot_directory.root)

  shutil.move(tmp_path, tar_location)

  return snapshot


def _fingerprint_files_in_tar(file_list, tar_location):
  """
  TODO: This could potentially be implemented by nuking any timestamp entries in
  the tar file, and then fingerprinting the entire thing.
  """
  hasher = sha1()
  with open_tar(tar_location, mode='r', errorlevel=1) as tar:
    for file in file_list.dependencies:
      hasher.update(file.path)
      hasher.update(tar.extractfile(file.path).read())
  return hasher.hexdigest()


def _snapshot_path(snapshot, archive_root):
  safe_mkdir(archive_root)
  tar_location = os.path.join(archive_root, '{}.tar'.format(snapshot.fingerprint))
  return tar_location


def _extract_snapshot(snapshot_archive_root, snapshot, sandbox_dir):
  with open_tar(_snapshot_path(snapshot, snapshot_archive_root), errorlevel=1) as tar:
    tar.extractall(sandbox_dir)


def _run_command(binary, sandbox_dir, process_request):
  command = binary.prefix_of_command() + tuple(process_request.args)
  logger.debug('Running command: "{}" in {}'.format(command, sandbox_dir))
  popen = subprocess.Popen(command,
                           stderr=subprocess.PIPE,
                           stdout=subprocess.PIPE,
                           cwd=sandbox_dir)
  # TODO At some point, we may want to replace this blocking wait with a timed one that returns
  # some kind of in progress state.
  popen.wait()
  logger.debug('Done running command in {}'.format(sandbox_dir))
  return popen


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


class Snapshot(datatype('Snapshot', ['fingerprint', 'dependencies'])):
  """A snapshot is a collection of Files and Dirs fingerprinted by their names/content.

  Snapshots are used to make it easier to isolate process execution by fixing the contents
  of the files being operated on and easing their movement to and from isolated execution
  sandboxes.
  """


class Binary(object):
  """Binary in the product graph.

  TODO these should use BinaryUtil to find binaries.
  """

  @abstractproperty
  def bin_path(self):
    pass

  def prefix_of_command(self):
    return tuple([self.bin_path])


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


class _SnapshotDirectory(datatype('_SnapshotDirectory', ['root'])):
  """Private singleton value for the snapshot directory."""


def snapshot_directory(project_tree):
  return _SnapshotDirectory(os.path.join(project_tree.build_root, '.snapshots'))


class SnapshottedProcess(object):
  """A static helper for defining a task rule to execute a snapshotted process."""

  def __new__(cls, *args):
    raise ValueError('Use `create` to declare a task function representing a process.')

  @staticmethod
  def create(product_type, binary_type, input_selectors, input_conversion, output_conversion):
    """TODO: Not clear that `binary_type` needs to be separate from the input selectors."""

    # Select the concatenation of the snapshot directory, binary, and input selectors.
    inputs = (Select(_SnapshotDirectory), Select(binary_type)) + tuple(input_selectors)

    # Apply the input/output conversions to a top-level process-execution function which
    # will receive all inputs, convert in, execute, and convert out.
    func = functools.partial(_snapshotted_process,
                             input_conversion,
                             output_conversion)
    func.__name__ = '{}_and_then_snapshotted_process_and_then_{}'.format(
        input_conversion.__name__, output_conversion.__name__
      )

    # Return a task triple that executes the function to produce the product type.
    return (product_type, inputs, func)


def create_snapshot_singletons(project_tree):
  def ptree(func):
    p = functools.partial(func, project_tree)
    p.__name__ = '{}_singleton'.format(func.__name__)
    return p
  return [
      (_SnapshotDirectory, ptree(snapshot_directory))
    ]


def create_snapshot_tasks(project_tree):
  def ptree(func):
    partial = functools.partial(func, project_tree, snapshot_directory(project_tree))
    partial.__name__ = '{}_task'.format(func.__name__)
    return partial
  return [
      (Snapshot, [Select(Files), Select(Dirs)], ptree(create_snapshot_archive)),
    ]
