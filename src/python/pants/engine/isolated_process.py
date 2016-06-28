# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess
from abc import abstractproperty

from pants.engine.fs import Files
from pants.engine.nodes import Node, Noop, Return, State, TaskNode, Throw, Waiting
from pants.engine.rule import Rule
from pants.engine.selectors import Select
from pants.util.contextutil import open_tar, temporary_dir
from pants.util.dirutil import safe_mkdir
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class Snapshot(datatype('Snapshot', ['archive'])):
  """Holds a reference to the archived snapshot of something."""


class Binary(datatype('Binary', [])):
  """Binary in the product graph.

  Still working out the contract here."""

  @abstractproperty
  def bin_path(self):
    pass

  def prefix_of_command(self):
    return tuple([self.bin_path])


class Checkout(datatype('Checkout', ['path'])):
  """Checkout directory of one or more snapshots."""


class SnapshottedProcessRequest(datatype('SnapshottedProcessRequest',
                                         ['args', 'snapshot_subjects', 'prep_fn'])):
  """Request for execution with binary args and snapshots to extract.

  args - Arguments to the binary being run.
  snapshot_subjects - Subjects for requesting snapshots that will be checked out into the work dir
                      for the process.
  prep_fn - escape hatch for manipulating the work dir.

            TODO come up with a better scheme for preparing for execution that's transparent to the engine.
  """

  def __new__(cls, args, snapshot_subjects=tuple(), prep_fn=None, **kwargs):
    if not isinstance(args, tuple):
      args = tuple(args)
    if not isinstance(snapshot_subjects, tuple):
      snapshot_subjects = tuple(snapshot_subjects)
    return super(SnapshottedProcessRequest, cls).__new__(cls, args, snapshot_subjects, prep_fn, **kwargs)


class SnapshottedProcessResult(datatype('SnapshottedProcessResult', ['stdout', 'stderr', 'exit_code'])):
  """Contains the stdout / stderr from executing a process."""


class UncacheableTaskNode(TaskNode):
  """A task node that isn't cacheable."""
  is_cacheable = False


class ProcessExecutionNode(datatype('ProcessNode', ['binary', 'process_request', 'checkout']),
                           Node):
  """Executes processes in a checkout directory."""

  is_cacheable = False
  is_inlineable = False
  variants = None

  def step(self, step_context):
    command = self.binary.prefix_of_command() + tuple(self.process_request.args)
    logger.debug('Running command: "{}" in {}'.format(command, self.checkout.path))

    popen = subprocess.Popen(command,
                             stderr=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             cwd=self.checkout.path)
    # TODO At some point, we may want to replace this blocking wait with a timed one that returns
    # some kind of in progress state.
    popen.wait()

    logger.debug('Done running command in {}'.format(self.checkout.path))

    return Return(
      SnapshottedProcessResult(popen.stdout.read(), popen.stderr.read(), popen.returncode)
    )


class ProcessOrchestrationNode(datatype('ProcessOrchestrationNode',
                                        ['subject', 'snapshotted_process']),
                               Node):
  """Wraps a process execution, preparing and tearing down the execution environment."""

  is_cacheable = True
  is_inlineable = False
  variants = None

  @property
  def product(self):
    return self.snapshotted_process.product_type

  def step(self, step_context):
    # Create the request from the request callback.
    task_state = step_context.get(self._request_task_node())

    if type(task_state) in (Waiting, Throw):
      return task_state
    elif type(task_state) is Noop:
      return Noop("Couldn't construct process request: {}".format(task_state))
    elif type(task_state) is not Return:
      State.raise_unrecognized(task_state)

    process_request = task_state.value

    # Get the binary.
    binary_state = step_context.get(self._binary_select_node(step_context))
    if type(binary_state) in (Waiting, Throw):
      return binary_state
    elif type(binary_state) is Noop:
      return Noop("Couldn't find binary: {}".format(binary_state))
    elif type(binary_state) is not Return:
      State.raise_unrecognized(binary_state)

    binary_value = binary_state.value

    # If the process requires snapshots, request a checkout with the requested snapshots applied.
    if process_request.snapshot_subjects:
      # TODO investigate converting this into either a dependency op or a projection.
      open_node = OpenCheckoutNode(process_request)
      state_open = step_context.get(open_node)
      if type(state_open) in (Waiting, Throw, Noop):
        return state_open

      checkout = state_open.value

      for snapshot_subject in process_request.snapshot_subjects:
        ss_apply_node = ApplyCheckoutNode(snapshot_subject, checkout)
        ss_state = step_context.get(ss_apply_node)
        if type(ss_state) is Return:
          pass # NB the return value here isn't interesting. We're purely interested in the
               # modifications taking place.
        elif type(ss_state) in (Waiting, Throw, Noop):
          return ss_state
      # All of the snapshots have been checked out now.
      if process_request.prep_fn:
        process_request.prep_fn(checkout)
    else:
      # If there are no things to snapshot, then do no snapshotting or checking out and just use the
      # project dir.
      checkout = Checkout(step_context.project_tree.build_root)

    exec_node = self._process_exec_node(binary_value, process_request, checkout)
    exec_state = step_context.get(exec_node)
    if type(exec_state) in (Waiting, Throw, Noop):
      return exec_state
    elif type(exec_state) is not Return:
      State.raise_unrecognized(exec_state)

    process_result = exec_state.value

    converted_output = self.snapshotted_process.output_conversion(process_result, checkout)

    # TODO clean up the checkout.

    return Return(converted_output)

  def _process_exec_node(self, binary_value, process_request, checkout):
    return ProcessExecutionNode(binary_value, process_request, checkout)

  def _binary_select_node(self, step_context):
    return step_context.select_node(Select(self.snapshotted_process.binary_type),
                                    # TODO figure out what these should be
                                    subject=None,
                                    variants=None)

  def _request_task_node(self):
    return UncacheableTaskNode(subject=self.subject,
                               product=SnapshottedProcessRequest,
                               variants=None,  # TODO figure out what this should be
                               func=self.snapshotted_process.input_conversion,
                               clause=self.snapshotted_process.input_selectors)

  def __repr__(self):
    return 'ProcessOrchestrationNode(subject={}, snapshotted_process={}' \
      .format(self.subject, self.snapshotted_process)

  def __str__(self):
    return repr(self)


class SnapshotNode(datatype('SnapshotNode', ['subject', 'variants']), Node):
  is_inlineable = False
  is_cacheable = True
  product = Snapshot

  def step(self, step_context):
    selector = Select(Files)
    node = step_context.select_node(selector, self.subject, self.variants)
    select_state = step_context.get(node)

    if type(select_state) in {Waiting, Noop, Throw}:
      return select_state
    elif type(select_state) is not Return:
      State.raise_unrecognized(select_state)

    # TODO Create / find snapshot directory via configuration.
    build_root = step_context.project_tree.build_root
    archive_dir = os.path.join(build_root, 'snapshots')
    safe_mkdir(archive_dir)

    file_list = select_state.value

    logger.debug('snapshotting for files: {}'.format(file_list))
    # TODO name snapshot archive based on subject, maybe.
    tar_location = os.path.join(archive_dir, 'my-tar.tar')

    with open_tar(tar_location, mode='w:gz') as tar:
      for file in file_list.dependencies:
        tar.add(os.path.join(build_root, file.path), file.path)

    return Return(Snapshot(tar_location))


class SnapshottingRule(Rule):
  input_selects = Select(Files)
  output_product_type = Snapshot

  def as_node(self, subject, product_type, variants):
    assert product_type == Snapshot
    return SnapshotNode(subject, variants)


class OpenCheckoutNode(datatype('CheckoutNode', ['subject']), Node):
  is_cacheable = True
  is_inlineable = False
  product = Checkout
  variants = None

  def step(self, step_context):
    logger.debug('Constructing checkout for {}'.format(self.subject))
    with temporary_dir(cleanup=False) as outdir:
      return Return(Checkout(outdir))


class ApplyCheckoutNode(datatype('CheckoutNode', ['subject', 'checkout']), Node):
  is_cacheable = False
  is_inlineable = False
  product = Checkout
  variants = None

  def step(self, step_context):
    node = step_context.select_node(Select(Snapshot), self.subject, None)
    select_state = step_context.get(node)
    if type(select_state) in {Waiting, Throw, Noop}:
      return select_state
    elif type(select_state) is not Return:
      State.raise_unrecognized(select_state)

    with open_tar(select_state.value.archive, errorlevel=1) as tar:
      tar.extractall(self.checkout.path)
    logger.debug('extracted {} snapshot to {}'.format(self.subject, self.checkout.path))
    return Return(self.checkout)
