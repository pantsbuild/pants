# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import Task
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.memo import memoized_property

from pants.contrib.node.subsystems.node_distribution import NodeDistribution
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.targets.npm_package import NpmPackage


class NodeTask(Task):

  @classmethod
  def subsystem_dependencies(cls):
    return (NodeDistribution.Factory,)

  @memoized_property
  def node_distribution(self):
    """A bootstrapped node distribution for use by node tasks."""
    return NodeDistribution.Factory.global_instance().create()

  @classmethod
  def is_npm_package(cls, target):
    """Returns `True` if the given target is an `NpmPackage`."""
    return isinstance(target, NpmPackage)

  @classmethod
  def is_node_module(cls, target):
    """Returns `True` if the given target is a `NodeModule`."""
    return isinstance(target, NodeModule)

  @classmethod
  def is_node_remote_module(cls, target):
    """Returns `True` if the given target is a `NodeRemoteModule`."""
    return isinstance(target, NodeRemoteModule)

  def execute_node(self, args, workunit_name=None, workunit_labels=None, **kwargs):
    """Executes node passing the given args.

    :param list args: The command line args to pass to `node`.
    :param string workunit_name: A name for the execution's work unit; defaults to 'node'.
    :param list workunit_labels: Any extra :class:`pants.base.workunit.WorkUnitLabel`s to apply.
    :param **kwargs: Any extra args to pass to :class:`subprocess.Popen`.
    :returns: A tuple of (returncode, command).
    :rtype: A tuple of (int,
            :class:`pants.contrib.node.subsystems.node_distribution.NodeDistribution.Command`)
    """
    node_command = self.node_distribution.node_command(args=args)
    return self._execute_command(node_command,
                                 workunit_name=workunit_name,
                                 workunit_labels=workunit_labels,
                                 **kwargs)

  def execute_npm(self, args, workunit_name=None, workunit_labels=None, **kwargs):
    """Executes npm passing the given args.

    :param list args: The command line args to pass to `npm`.
    :param string workunit_name: A name for the execution's work unit; defaults to 'npm'.
    :param list workunit_labels: Any extra :class:`pants.base.workunit.WorkUnitLabel`s to apply.
    :param **kwargs: Any extra args to pass to :class:`subprocess.Popen`.
    :returns: A tuple of (returncode, command).
    :rtype: A tuple of (int,
            :class:`pants.contrib.node.subsystems.node_distribution.NodeDistribution.Command`)
    """

    npm_command = self.node_distribution.npm_command(args=args)
    return self._execute_command(npm_command,
                                 workunit_name=workunit_name,
                                 workunit_labels=workunit_labels,
                                 **kwargs)

  def _execute_command(self, command, workunit_name=None, workunit_labels=None, **kwargs):
    workunit_name = workunit_name or command.executable
    workunit_labels = {WorkUnitLabel.TOOL} | set(workunit_labels or ())
    with self.context.new_workunit(name=workunit_name,
                                   labels=workunit_labels,
                                   cmd=str(command)) as workunit:
      process = command.run(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'),
                            **kwargs)
      returncode = process.wait()
      workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
      return returncode, command
