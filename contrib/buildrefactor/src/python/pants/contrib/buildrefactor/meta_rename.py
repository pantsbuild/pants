# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from collections import defaultdict

from pants.base.specs import DescendantAddresses
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.task.task import Task

from pants.contrib.buildrefactor.buildozer import Buildozer


logger = logging.getLogger(__name__)


class MetaRename(Task):
  """Rename a target and update its dependees' dependencies with the new target name

  Provides a mechanism for renaming the target's name within its local BUILD file.
  Also renames the target wherever it's specified as a dependency.
  """

  @classmethod
  def register_options(cls, register):
    super(MetaRename, cls).register_options(register)

    register('--from', type=str, advanced=True, default=None, help='The old dependency name to change')
    register('--to', type=str, advanced=True, default=None, help='The new name for the dependency')

  def __init__(self, *args, **kwargs):
    super(MetaRename, self).__init__(*args, **kwargs)

    self._from_address = Address.parse(self.get_options()['from'])
    self._to_address = Address.parse(self.get_options().to)

  def execute(self):
    self.update_dependee_references()
    self.update_original_build_name()

  def update_dependee_references(self):
    dependee_targets = self.dependency_graph()[
      Target(name=self._from_address.target_name, address=self._from_address, build_graph=[], **{})
    ]

    logging.disable(logging.WARNING)

    for concrete_target in dependee_targets:
      for formats in [
        { 'from': self._from_address.spec, 'to': self._to_address.spec },
        { 'from': ':{}'.format(self._from_address.target_name), 'to': ':{}'.format(self._to_address.target_name) }
      ]:
        Buildozer.execute_binary(
          'replace dependencies {} {}'.format(formats['from'], formats['to']),
          spec=concrete_target.address.spec
        )

    logging.disable(logging.NOTSET)

  def update_original_build_name(self):
    Buildozer.execute_binary('set name {}'.format(self._to_address.target_name), spec=self._from_address.spec)

  def dependency_graph(self, scope=''):
    dependency_graph = defaultdict(set)

    for address in self.context.build_graph.inject_specs_closure([DescendantAddresses(scope)]):
      target = self.context.build_graph.get_target(address)

      for dependency in target.dependencies:
        dependency_graph[dependency].add(target.concrete_derived_from)

    return dependency_graph
