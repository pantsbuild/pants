# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import inspect


from collections import defaultdict
from pants.util.process_handler import subprocess

from pants.base.specs import DescendantAddresses
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.task.task import Task

from pants.contrib.buildrefactor.buildozer import Buildozer


logger = logging.getLogger(__name__)

class MetaRelocate(Task):
  """Rename a target and update its dependees' dependencies with the new target name

  Provides a mechanism for renaming the target's name within its local BUILD file.
  Also renames the target wherever it's specified as a dependency.
  """

  @classmethod
  def register_options(cls, register):
    super(MetaRelocate, cls).register_options(register)
    register('--to', type=str, advanced=True, default=None, help='The new location of the target')

  def __init__(self, *args, **kwargs):
    super(MetaRelocate, self).__init__(*args, **kwargs)
    if len(self.context.target_roots) > 1:
      raise TaskError('More than one target specified:\n{}'.format(str(self.context.target_roots)))
    self._to_address = Address.parse(self.get_options().to)
    self._target_to_move = self.context.target_roots[0]

  def execute(self):
    self.update_dependee_references()
    if self._target_to_move.has_sources:
      self.move_sources()
    self.add_to_BUILD()
    self.remove_from_BUILD()

  def move_sources(self):
    sources = self._target_to_move.sources_relative_to_target_base()

    for source in sources:
      try:
        os.rename(os.path.join(self._target_to_move.address.spec_path, source),
          os.path.join(self._to_address.spec_path, source))
      except OSError as err:
        print(err)

  def add_to_BUILD(self):
    with open('{}/BUILD'.format(self._to_address.spec_path), "a") as dest_file:
      dest_file.write(Buildozer.execute_binary('print rule', spec=self._target_to_move.address.spec, return_flag=True))

  def remove_from_BUILD(self):
    Buildozer.execute_binary('delete', spec=self._target_to_move.address.spec)

  def update_dependee_references(self):
    dependee_targets = self.dependency_graph()[self._target_to_move]

    for concrete_target in dependee_targets:
      if concrete_target.address.spec_path == self._target_to_move.address.spec_path:
        Buildozer.execute_binary('replace dependencies :{} {}:{}'.format(self._target_to_move.name, self._to_address.spec_path, self._target_to_move.name), spec=concrete_target.address.spec, suppress_warnings=True)
      elif concrete_target.address.spec_path == self._to_address.spec_path:
        Buildozer.execute_binary('replace dependencies {} :{}'.format(self._target_to_move.address.spec, self._target_to_move.name), spec=concrete_target.address.spec, suppress_warnings=True)
      else:
        for formats in [
          { 'from': self._target_to_move.address.spec, 'to': self._to_address.spec },
          { 'from': ':{}'.format(self._target_to_move.name), 'to': ':{}'.format(self._target_to_move.name) }
        ]:
          Buildozer.execute_binary(
            'replace dependencies {} {}'.format(formats['from'], formats['to']),
            spec=concrete_target.address.spec, suppress_warnings=True,
          )

  def dependency_graph(self, scope=''):
    dependency_graph = defaultdict(set)

    for address in self.context.build_graph.inject_specs_closure([DescendantAddresses(scope)]):
      target = self.context.build_graph.get_target(address)

      for dependency in target.dependencies:
        dependency_graph[dependency].add(target.concrete_derived_from)

    return dependency_graph
