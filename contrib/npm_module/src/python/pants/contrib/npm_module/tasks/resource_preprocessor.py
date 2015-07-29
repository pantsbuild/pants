# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod, abstractproperty

from pants.contrib.npm_module.targets.gen_resources import GenResources

from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.task import Task
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError


class ResourcePreprocessor(Task):
  """ Processes GenResource targets
  """

  class ResourcePreprocessorError(Exception):
     """Indicates a ResourceProcessor Error"""
     def __init__(self, *args, **kwargs):
       super(ResourcePreprocessor.ResourcePreprocessorError, self).__init__(*args, **kwargs)

  def is_processable_target(self, target):
    return (isinstance(target, GenResources) and
            self.processor_name in target.preprocessors and
            not self.processor_name in target.processed)

  def get_unprocessed(self, target):
    return list(target.preprocessors.difference(target.processed))

  def execute(self):
    targets = self.context.targets(predicate=self.is_processable_target)
    for target in targets:
      try:
        files = self.run_processor(target)
        target.processed.add(self.processor_name)
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
