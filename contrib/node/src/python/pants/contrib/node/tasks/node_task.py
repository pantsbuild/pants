# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.task.task import Task
from pants.util.memo import memoized_property

from pants.contrib.node.subsystems.node_distribution import NodeDistribution
from pants.contrib.node.subsystems.package_managers import PACKAGE_MANAGER_YARNPKG
from pants.contrib.node.targets.node_bundle import NodeBundle
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_package import NodePackage
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.targets.node_test import NodeTest


class NodeTask(Task):

  @classmethod
  def subsystem_dependencies(cls):
    return super(NodeTask, cls).subsystem_dependencies() + (NodeDistribution.scoped(cls),)

  @memoized_property
  def node_distribution(self):
    """A bootstrapped node distribution for use by node tasks."""
    return NodeDistribution.scoped_instance(self)

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

  @classmethod
  def is_node_bundle(cls, target):
    """Returns `True` if given target is a `NodeBundle`."""
    return isinstance(target, NodeBundle)

  def get_package_manager(self, target=None):
    """Returns package manager for target argument or global config."""
    package_manager = None
    if target:
      target_package_manager_field = target.payload.get_field('package_manager')
      if target_package_manager_field:
        package_manager = target_package_manager_field.value
    return self.node_distribution.get_package_manager(package_manager=package_manager)

  def execute_node(self, args, workunit_name, workunit_labels=None, node_paths=None):
    """Executes node passing the given args.

    :param list args: The command line args to pass to `node`.
    :param string workunit_name: A name for the execution's work unit; defaults to 'node'.
    :param list workunit_labels: Any extra :class:`pants.base.workunit.WorkUnitLabel`s to apply.
    :param list node_paths: A list of node module paths to be included.
    :returns: A tuple of (returncode, command).
    :rtype: A tuple of (int,
            :class:`pants.contrib.node.subsystems.node_distribution.NodeDistribution.Command`)
    """
    node_command = self.node_distribution.node_command(args=args, node_paths=node_paths)
    return self._execute_command(node_command,
                                 workunit_name=workunit_name,
                                 workunit_labels=workunit_labels)

  def add_package(
    self, target=None, package_manager=None, 
    package=None, type_option=None, version_option=None,
    node_paths=None, workunit_name=None, workunit_labels=None):
    """Add an additional package using requested package_manager."""
    package_manager = package_manager or self.get_package_manager(target=target)
    command = package_manager.add_package(
      package,
      type_option=type_option,
      version_option=version_option,
      node_paths=node_paths,
    )
    return self._execute_command(
      command, workunit_name=workunit_name, workunit_labels=workunit_labels)

  def install_module(
    self, target=None, package_manager=None, 
    install_optional=False, production_only=False, force=False, 
    node_paths=None, frozen_lockfile=None, workunit_name=None, workunit_labels=None):
    """Installs node module using requested package_manager."""
    package_manager = package_manager or self.get_package_manager(target=target)
    command = package_manager.install_module(
      install_optional=install_optional,
      force=force,
      production_only=production_only,
      node_paths=node_paths,
      frozen_lockfile=frozen_lockfile
    )
    return self._execute_command(
      command, workunit_name=workunit_name, workunit_labels=workunit_labels)

  def run_script(
    self, script_name, target=None, package_manager=None, script_args=None, node_paths=None,
    workunit_name=None, workunit_labels=None):
    package_manager = package_manager or self.get_package_manager(target=target)
    command = package_manager.run_script(
      script_name,
      script_args=script_args,
      node_paths=node_paths,
    )
    return self._execute_command(
      command, workunit_name=workunit_name, workunit_labels=workunit_labels)

  def run_cli(self, cli, args=None, node_paths=None, workunit_name=None, workunit_labels=None):
    package_manager = self.node_distribution.get_package_manager(
      package_manager=PACKAGE_MANAGER_YARNPKG)
    command = package_manager.run_cli(cli, args=args, node_paths=node_paths)
    return self._execute_command(
      command, workunit_name=workunit_name, workunit_labels=workunit_labels)

  def _execute_command(self, command, workunit_name=None, workunit_labels=None):
    """Executes a node or npm command via self._run_node_distribution_command.

    :param NodeDistribution.Command command: The command to run.
    :param string workunit_name: A name for the execution's work unit; default command.executable.
    :param list workunit_labels: Any extra :class:`pants.base.workunit.WorkUnitLabel`s to apply.
    :returns: A tuple of (returncode, command).
    :rtype: A tuple of (int,
            :class:`pants.contrib.node.subsystems.node_distribution.NodeDistribution.Command`)
    """
    workunit_name = workunit_name or command.executable
    workunit_labels = {WorkUnitLabel.TOOL} | set(workunit_labels or ())
    with self.context.new_workunit(name=workunit_name,
                                   labels=workunit_labels,
                                   cmd=str(command)) as workunit:
      returncode = self._run_node_distribution_command(command, workunit)
      workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
      return returncode, command

  def _run_node_distribution_command(self, command, workunit):
    """Runs a NodeDistribution.Command for _execute_command and returns its return code.

    Passes any additional kwargs to command.run (which passes them, modified, to subprocess.Popen).
    Override this in a Task subclass to do something more complicated than just calling
    command.run() and returning the result of wait().

    :param NodeDistribution.Command command: The command to run.
    :param WorkUnit workunit: The WorkUnit the command is running under.
    :returns: returncode
    :rtype: int
    """
    process = command.run(stdout=workunit.output('stdout'),
                          stderr=workunit.output('stderr'))
    return process.wait()
