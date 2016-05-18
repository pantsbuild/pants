# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.task.task import Task
from pants.util.memo import memoized_property

from pants.contrib.node.subsystems.node_distribution import NodeDistribution
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_package import NodePackage
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.targets.node_test import NodeTest


class NodeTask(Task):

  @classmethod
  def subsystem_dependencies(cls):
    return (NodeDistribution.Factory,)

  @memoized_property
  def node_distribution(self):
    """A bootstrapped node distribution for use by node tasks."""
    return NodeDistribution.Factory.global_instance().create()

  @classmethod
  def is_node_package(cls, target):
    """Returns `True` if the given target is an `NodePackage`."""
    return isinstance(target, NodePackage)

  @classmethod
  def is_node_module(cls, target):
    """Returns `True` if the given target is a `NodeModule`."""
    return isinstance(target, NodeModule)

  @classmethod
  def is_node_remote_module(cls, target):
    """Returns `True` if the given target is a `NodeRemoteModule`."""
    return isinstance(target, NodeRemoteModule)

  @classmethod
  def is_node_test(cls, target):
    """Returns `True` if the given target is a `NodeTest`."""
    return isinstance(target, NodeTest)

  def execute_node(self, args, workunit_name=None, workunit_labels=None, **kwargs):
    """Executes node passing the given args.

    :param list args: The command line args to pass to `node`.
    :param string workunit_name: A name for the execution's work unit; defaults to 'node'.
    :param list workunit_labels: Any extra :class:`pants.base.workunit.WorkUnitLabel`s to apply.
    :param **kwargs: Any extra kwargs to pass to the subprocess.Popen executing node.
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
    :param **kwargs: Any extra kwargs to pass to the subprocess.Popen executing npm.
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
    """Executes a node or npm command via self._run_node_distribution_command.

    :param NodeDistribution.Command command: The command to run.
    :param string workunit_name: A name for the execution's work unit; default command.executable.
    :param list workunit_labels: Any extra :class:`pants.base.workunit.WorkUnitLabel`s to apply.
    :param **kwargs: Any extra kwargs to pass to the subprocess.Popen executing node or npm.
    :returns: A tuple of (returncode, command).
    :rtype: A tuple of (int,
            :class:`pants.contrib.node.subsystems.node_distribution.NodeDistribution.Command`)
    """
    workunit_name = workunit_name or command.executable
    workunit_labels = {WorkUnitLabel.TOOL} | set(workunit_labels or ())
    with self.context.new_workunit(name=workunit_name,
                                   labels=workunit_labels,
                                   cmd=str(command)) as workunit:
      returncode = self._run_node_distribution_command(command, workunit, **kwargs)
      workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
      return returncode, command

  def _run_node_distribution_command(self, command, workunit, **kwargs):
    """Runs a NodeDistribution.Command for _execute_command and returns its return code.

    Passes any additional kwargs to command.run (which passes them, modified, to subprocess.Popen).
    Override this in a Task subclass to do something more complicated than just calling
    command.run() and returning the result of wait().

    :param NodeDistribution.Command command: The command to run.
    :param WorkUnit workunit: The WorkUnit the command is running under.
    :param **kwargs: Any extra kwargs to pass to the subprocess.Popen executing node or npm.
    :returns: returncode
    :rtype: int
    """
    process = command.run(stdout=workunit.output('stdout'),
                          stderr=workunit.output('stderr'),
                          **kwargs)
    return process.wait()
