# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil
import subprocess
from abc import abstractproperty
from hashlib import sha1

from pants.engine.fs import Files
from pants.engine.nodes import Node, Noop, Return, Runnable, State, Throw, Waiting
from pants.engine.selectors import Select, SelectDependencies
from pants.util.contextutil import open_tar, temporary_dir, temporary_file_path
from pants.util.dirutil import safe_mkdir
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


def _create_snapshot_archive(file_list, step_context):
  logger.debug('snapshotting files: {}'.format(file_list))

  # Constructs the snapshot tar in a temporary location, then fingerprints it and moves it to the final path.
  with temporary_file_path(cleanup=False) as tmp_path:
    with open_tar(tmp_path, mode='w') as tar:
      for file in file_list.dependencies:
        # TODO handle GitProjectTree. Using add this this will fail with a non-filesystem project tree.
        tar.add(os.path.join(step_context.project_tree.build_root, file.path), file.path)
    snapshot = Snapshot(_fingerprint_files_in_tar(file_list, tmp_path))
  tar_location = _snapshot_path(snapshot, step_context.snapshot_archive_root)

  shutil.move(tmp_path, tar_location)

  return snapshot


def _fingerprint_files_in_tar(file_list, tar_location):
  hasher = sha1()
  with open_tar(tar_location, mode='r', errorlevel=1) as tar:
    for file in file_list.dependencies:
      hasher.update(file.path)
      hasher.update(tar.extractfile(file.path).read())
  return hasher.hexdigest()


def _snapshot_path(snapshot, archive_root):
  # TODO Consider naming snapshot archive based also on the subject and not just the fingerprint of the contained files.
  safe_mkdir(archive_root)
  tar_location = os.path.join(archive_root, '{}.tar'.format(snapshot.fingerprint))
  return tar_location


def _extract_snapshot(snapshot_archive_root, snapshot, sandbox_dir, subject):
  with open_tar(_snapshot_path(snapshot, snapshot_archive_root), errorlevel=1) as tar:
    tar.extractall(sandbox_dir)
  logger.debug('extracted {} snapshot to {}'.format(subject, sandbox_dir))


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


def _execute(process):
  process_request = process.request
  # TODO resolve what to do with output files, then make these tmp dirs cleaned up.
  with temporary_dir(cleanup=False) as sandbox_dir:
    if process_request.snapshot_subjects:
      snapshots_and_subjects = zip(process.snapshot_subjects_values, process_request.snapshot_subjects)
      for snapshot, subject in snapshots_and_subjects:
        _extract_snapshot(process.snapshot_archive_root, snapshot, sandbox_dir, subject)

    # All of the snapshots have been checked out now.
    if process_request.directories_to_create:
      for d in process_request.directories_to_create:
        safe_mkdir(os.path.join(sandbox_dir, d))

    popen = _run_command(process.binary, sandbox_dir, process_request)

    process_result = SnapshottedProcessResult(popen.stdout.read(), popen.stderr.read(), popen.returncode)
    if process_result.exit_code != 0:
      raise Exception('Running {} failed with non-zero exit code: {}'.format(process.binary,
                                                                             process_result.exit_code))

    return process.output_conversion(process_result, sandbox_dir)


class Snapshot(datatype('Snapshot', ['fingerprint'])):
  """A snapshot of a collection of files fingerprinted by their contents.

  Snapshots are used to make it easier to isolate process execution by fixing the contents of the files being operated
  on and easing their movement to and from isolated execution sandboxes.
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
                                         ['args', 'snapshot_subjects', 'directories_to_create'])):
  """Request for execution with binary args and snapshots to extract."""

  def __new__(cls, args, snapshot_subjects=tuple(), directories_to_create=tuple(), **kwargs):
    """

    :param args: Arguments to the binary being run.
    :param snapshot_subjects: Subjects used to request snapshots that will be checked out into the sandbox.
    :param directories_to_create: Directories to ensure exist in the sandbox before execution.
    """
    if not isinstance(args, tuple):
      raise ValueError('args must be a tuple.')
    if not isinstance(snapshot_subjects, tuple):
      raise ValueError('snapshot_subjects must be a tuple.')
    if not isinstance(directories_to_create, tuple):
      raise ValueError('directories_to_create must be a tuple.')
    return super(SnapshottedProcessRequest, cls).__new__(cls, args, snapshot_subjects, directories_to_create, **kwargs)


class SnapshottedProcessResult(datatype('SnapshottedProcessResult', ['stdout', 'stderr', 'exit_code'])):
  """Contains the stdout, stderr and exit code from executing a process."""


class _Process(datatype('_Process', ['snapshot_archive_root',
                                     'request',
                                     'binary',
                                     'snapshot_subjects_values',
                                     'output_conversion'])):
  """All (pickleable) arguments for the execution of a sandboxed process."""


class ProcessExecutionNode(datatype('ProcessExecutionNode', ['subject', 'variants', 'snapshotted_process']), Node):
  """Wraps a process execution, preparing and tearing down the execution environment."""

  is_cacheable = True
  is_inlineable = False

  @property
  def product(self):
    return self.snapshotted_process.product_type

  def step(self, step_context):
    waiting_nodes = []
    # Get the binary.
    binary_state = step_context.select_for(Select(self.snapshotted_process.binary_type),
                                           subject=self.subject,
                                           variants=self.variants)
    if type(binary_state) is Throw:
      return binary_state
    elif type(binary_state) is Waiting:
      waiting_nodes.extend(binary_state.dependencies)
    elif type(binary_state) is Noop:
      return Noop("Couldn't find binary: {}".format(binary_state))
    elif type(binary_state) is not Return:
      State.raise_unrecognized(binary_state)

    # Create the request from the request callback after resolving its input clauses.
    input_values = []
    for input_selector in self.snapshotted_process.input_selectors:
      sn_state = step_context.select_for(input_selector, self.subject, self.variants)
      if type(sn_state) is Waiting:
        waiting_nodes.extend(sn_state.dependencies)
      elif type(sn_state) is Return:
        input_values.append(sn_state.value)
      elif type(sn_state) is Noop:
        if input_selector.optional:
          input_values.append(None)
        else:
          return Noop('Was missing value for (at least) input {}'.format(input_selector))
      elif type(sn_state) is Throw:
        return sn_state
      else:
        State.raise_unrecognized(sn_state)

    if waiting_nodes:
      return Waiting(waiting_nodes)

    # Now that we've returned on waiting, we can assume that relevant inputs have values.
    try:
      process_request = self.snapshotted_process.input_conversion(*input_values)
    except Exception as e:
      return Throw(e)

    # Request snapshots for the snapshot_subjects from the process request.
    snapshot_subjects_value = []
    if process_request.snapshot_subjects:
      snapshot_subjects_state = step_context.select_for(SelectDependencies(Snapshot,
                                                                           SnapshottedProcessRequest,
                                                                           'snapshot_subjects',
                                                                           field_types=(Files,)),
                                                        process_request,
                                                        self.variants)
      if type(snapshot_subjects_state) is not Return:
        return snapshot_subjects_state
      snapshot_subjects_value = snapshot_subjects_state.value

    # Ready to run.
    execution = _Process(step_context.snapshot_archive_root,
                         process_request,
                         binary_state.value,
                         snapshot_subjects_value,
                         self.snapshotted_process.output_conversion)
    return Runnable(_execute, (execution,))


class SnapshotNode(datatype('SnapshotNode', ['subject', 'variants']), Node):
  is_inlineable = False
  is_cacheable = False
  product = Snapshot

  @classmethod
  def create(cls, subject, variants):
    return SnapshotNode(subject, variants)

  def step(self, step_context):
    select_state = step_context.select_for(Select(Files), self.subject, self.variants)

    if type(select_state) in {Waiting, Noop, Throw}:
      return select_state
    elif type(select_state) is not Return:
      State.raise_unrecognized(select_state)
    file_list = select_state.value

    snapshot = _create_snapshot_archive(file_list, step_context)

    return Return(snapshot)
