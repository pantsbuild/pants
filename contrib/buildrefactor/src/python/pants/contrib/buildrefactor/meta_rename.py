# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.specs import DescendantAddresses
from pants.build_graph.address import Address
from pants.contrib.buildrefactor.buildozer import Buildozer
from pants.task.task import Task


class MetaRename(Task):
  """Rename a target for its dependents

  Provides a mechanism for renaming the target's name within its local BUILD file.
  Also renames the target for its addresses wherever it's specified as a dependency.
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
    dependency_graph = self.dependency_graph()
    dependent_addresses = dependency_graph[
      ScalaLibrary(name=self._from_address.target_name, address=self._from_address, build_graph=[], **{})
    ]

    for address in dependent_addresses:
      try:
        Buildozer.execute_binary(
          'replace dependencies {}:{} {}:{}'.format(
            self._from_address.spec_path, self._from_address._target_name,
            self._to_address.spec_path, self._to_address.target_name),
          address=address
        )
      except Exception:
        Buildozer.execute_binary(
          'replace dependencies :{} :{}'.format(self._from_address.target_name, self._to_address.target_name),
          address=address
        )

  def update_original_build_name(self):
    Buildozer.execute_binary('set name {}'.format(self._to_address.target_name), address=self._from_address)

  def dependency_graph(self, scope=''):
    dependency_graph = defaultdict(set)

    for address in self.context.build_graph.inject_specs_closure([DescendantAddresses(scope)]):
      target = self.context.build_graph.get_target(address)

      for dependency in target.dependencies:
        dependency_graph[dependency].add(address)

    return dependency_graph
