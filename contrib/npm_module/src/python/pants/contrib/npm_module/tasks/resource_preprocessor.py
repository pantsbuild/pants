# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from abc import abstractmethod, abstractproperty

from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.binaries.node_binary import NodeBinary

from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.task import Task
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.contextutil import pushd
from pants.util.dirutil import safe_mkdir


class ResourcePreprocessor(Task):
  """Processes GenResource targets"""


  class ResourcePreprocessorError(Exception):
     """Indicates a ResourceProcessor Error"""

  @classmethod
  def prepare(cls, options, round_manager):
    super(ResourcePreprocessor, cls).prepare(options, round_manager)

  def __init__(self, *args, **kwargs):
    super(ResourcePreprocessor, self).__init__(*args, **kwargs)
    self._module_name = self.MODULE_NAME
    self._module_version = self.MODULE_VERSION
    self._module_executable = self.MODULE_EXECUTABLE
    self._cachedir = os.path.join(self.workdir, self._module_name, self._module_version)

  def is_processable_target(self, target):
    return (isinstance(target, GenResources) and self.processor_name in target.preprocessors)

  @classmethod
  def task_subsystems(cls):
      return super(ResourcePreprocessor, cls).task_subsystems() + (NodeBinary.NodeFactory,)

  def get_unprocessed(self, target):
    return list(target.preprocessors.difference(target.processed))

  def execute(self):
    targets = self.context.targets(predicate=self.is_processable_target)
    for target in targets:
      try:
        files = self.run_processor(target)
        if files:
          self._create_target(target, files)
      except ResourcePreprocessor.ResourcePreprocessorError as e:
        raise TaskError('Preprocessor {processor_name} on target {target} failed due to '
                        'exception {exp}'.format(processor_name=self.processor_name,
                                                 target=target,
                                                 exp=e))

  def _create_target(self, target, generated_files):
    relative_outdir = os.path.relpath(self.workdir, self.buildroot)
    syn_address = SyntheticAddress(spec_path=relative_outdir,
                                   target_name='{name}-gen-{id}'.format(name=target.name,
                                                                        id=self.processor_name))
    remaining_preprocessors = self.get_unprocessed(target)

    if remaining_preprocessors:
      new_target = self.context.add_new_target(syn_address,
                                               GenResources,
                                               sources=generated_files,
                                               preprocessors=remaining_preprocessors,
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

  @abstractmethod
  def run_processor(self, target):
    """Run the preprocessor."""

  @abstractproperty
  def processor_name(self):
    """Return processor name"""

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
        raise ResourcePreprocessor.ResourcePreprocessorError('Could not install module ({0})'
                                                             .format(self.module_name))

  def execute_npm_module(self, target):
    node_binary_path = NodeBinary.NodeFactory.scoped_instance(self).create().path
    node_environ = os.environ.copy()
    node_environ['PATH'] = os.pathsep.join([node_binary_path, node_environ['PATH']])
    if not os.path.exists(self.cachedir):
      safe_mkdir(self.cachedir)
      with pushd(self.cachedir):
        self._install_module(node_environ)
    with pushd(self.module_path):
      self.context.log.debug('Changing current directory to {0}'.format(self.cachedir))
      files = self.execute_cmd(target, node_environ)
      return files