# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from collections import defaultdict

from pants.base.specs import DescendantAddresses
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.task.task import Task

from pants.contrib.buildrefactor.buildozer_binary import BuildozerBinary


logger = logging.getLogger(__name__)


class MetaRename(Task):
  """Rename a target and update its dependees' dependencies with the new target name

  Provides a mechanism for renaming the target's name within its local BUILD file.
  Also renames the target wherever it's specified as a dependency.
  """

  @classmethod
  def subsystem_dependencies(cls):
    return super(MetaRename, cls).subsystem_dependencies() + (BuildozerBinary.scoped(cls),)

  @classmethod
  def register_options(cls, register):
    super(MetaRename, cls).register_options(register)

    register('--from', type=str, default=None, help='The old dependency name to change')
    register('--to', type=str, default=None, help='The new name for the dependency')

  def __init__(self, *args, **kwargs):
    super(MetaRename, self).__init__(*args, **kwargs)

    self._from_address = Address.parse(self.get_options()['from'])
    self._to_address = Address.parse(self.get_options().to)

  def execute(self):
    self.update_dependee_references()
    self.update_original_build_name()

  def update_dependee_references(self):
    dependee_targets = self.dependency_graph()[
      # TODO: The **{} seems unnecessary.
      Target(name=self._from_address.target_name, address=self._from_address, build_graph=self.context.build_graph, **{})
    ]

    logging.disable(logging.WARNING)

    buildozer_binary = BuildozerBinary.scoped_instance(self)
    for concrete_target in dependee_targets:
      for formats in [
        { 'from': self._from_address.spec, 'to': self._to_address.spec },
        { 'from': ':{}'.format(self._from_address.target_name), 'to': ':{}'.format(
          self._to_address.target_name) }
      ]:
        buildozer_binary.execute(
          'replace dependencies {} {}'.format(formats['from'], formats['to']),
          spec=concrete_target.address.spec,
          context=self.context
        )

    logging.disable(logging.NOTSET)

  def update_original_build_name(self):
    BuildozerBinary.scoped_instance(self).execute(
      'set name {}'.format(self._to_address.target_name),
      spec=self._from_address.spec,
      context=self.context)

  def dependency_graph(self, scope=''):
    dependency_graph = defaultdict(set)

    for address in self.context.build_graph.inject_specs_closure([DescendantAddresses(scope)]):
      target = self.context.build_graph.get_target(address)

      for dependency in target.dependencies:
        dependency_graph[dependency].add(target.concrete_derived_from)

    return dependency_graph
