# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from abc import abstractproperty

from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.binaries.node_binary import NodeBinary

from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.task import Task
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.contextutil import pushd
from pants.util.dirutil import safe_mkdir


class Transpiler(Task):
  """Processes GenResource targets"""


  class TranspilerError(Exception):
     """Indicates a ResourceProcessor Error"""

  @classmethod
  def prepare(cls, options, round_manager):
    super(Transpiler, cls).prepare(options, round_manager)

  def __init__(self, *args, **kwargs):
    super(Transpiler, self).__init__(*args, **kwargs)
    self._module_name = self.MODULE_NAME
    self._module_version = self.MODULE_VERSION
    self._module_executable = self.MODULE_EXECUTABLE
    self._cachedir = os.path.join(self.workdir, self._module_name, self._module_version)

  def is_processable_target(self, target):
    return (isinstance(target, GenResources) and self.transpiler_name in target.transpilers)

  @classmethod
  def task_subsystems(cls):
      return super(Transpiler, cls).task_subsystems() + (NodeBinary.NodeFactory,)

  def execute(self):
    targets = self.context.targets(predicate=self.is_processable_target)
    for target in targets:
      try:
        files = self.run_transpiler(target)
        if files:
          self._create_target(target, files)
      except Transpiler.TranspilerError as e:
        raise TaskError('Transpiler {transpiler_name} on target {target} failed due to '
                        'exception {exp}'.format(transpiler_name=self.transpiler_name,
                                                 target=target,
                                                 exp=e))

  def _create_target(self, target, generated_files):
    relative_outdir = os.path.relpath(self.workdir, self.buildroot)
    syn_address = SyntheticAddress(spec_path=relative_outdir,
                                   target_name='{name}-gen-{id}'.format(name=target.name,
                                                                        id=self.transpiler_name))
    remaining_transpilers = target.transpilers
    remaining_transpilers.remove(self.transpiler_name)
    if remaining_transpilers:
      new_target = self.context.add_new_target(syn_address,
                                               GenResources,
                                               sources=generated_files,
                                               transpilers=remaining_transpilers,
                                               gen_resource_path=target.gen_resource_path,
                                               derived_from=target)
    else:
      new_target = self.context.add_new_target(syn_address,
                                               Resources,
                                               sources=generated_files,
                                               derived_from=target)
    for dependent in self.context.build_graph.dependents_of(target.address):
      self.context.build_graph.inject_dependency(dependent,
                                                 new_target.address)

  @property
  def buildroot(self):
    return get_buildroot()

  @abstractproperty
  def transpiler_name(self):
    """Return transpiler name"""

  @property
  def cachedir(self):
    """Directory where module is cached"""
    return self._cachedir

  @property
  def module_path(self):
      return os.path.join(self.cachedir, 'node_modules', self.module_name)

  @property
  def module_name(self):
    """Name of the NPM Module"""
    return self._module_name

  @property
  def module_version(self):
    """Name of the NPM Module"""
    return self._module_version

  @property
  def module_executable(self):
    """Path of the Executable"""
    return self._module_executable

  def _install_module(self, node_environ):
    self.context.log.debug('Installing npm module {0}'.format(self._module_name))
    cmd = ['npm', 'install', '{0}@{1}'.format(self.module_name, self.module_version)]
    process = subprocess.Popen(cmd, env=node_environ)
    result = process.wait()
    if result != 0:
      raise Transpiler.TranspilerError('Could not install module ({0})'
                                       .format(self.module_name))

  def run_transpiler(self, target):
    node_binary_path = NodeBinary.NodeFactory.scoped_instance(self).create().path
    node_environ = os.environ.copy()
    node_environ['PATH'] = os.pathsep.join([node_binary_path, node_environ['PATH']])
    if not os.path.exists(self.module_path):
      safe_mkdir(self.cachedir)
      with pushd(self.cachedir):
        self._install_module(node_environ)
    with pushd(self.module_path):
      self.context.log.debug('Changing current directory to {0}'.format(self.cachedir))
      files = self.execute_cmd(target, node_environ)
      return files