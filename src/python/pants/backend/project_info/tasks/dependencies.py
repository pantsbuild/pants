# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.base.exceptions import TaskError
from pants.base.payload_field import JarsField, PythonRequirementsField


class Dependencies(ConsoleTask):
  """Generates a textual list (using the target format) for the dependency set of a target."""

  @staticmethod
  def _is_jvm(target):
    return target.is_jvm or isinstance(target, JvmApp)

  @classmethod
  def register_options(cls, register):
    super(Dependencies, cls).register_options(register)
    register('--internal-only', default=False, action='store_true',
             help='Specifies that only internal dependencies should be included in the graph '
                  'output (no external jars).')
    register('--external-only', default=False, action='store_true',
             help='Specifies that only external dependencies should be included in the graph '
                  'output (only external jars).')
    register('--transitive', default=True, action='store_true',
             help='List transitive dependencies. Disable to only list dependencies defined '
                  'in target BUILD file(s).')

  def __init__(self, *args, **kwargs):
    super(Dependencies, self).__init__(*args, **kwargs)

    self.is_internal_only = self.get_options().internal_only
    self.is_external_only = self.get_options().external_only
    self._transitive = self.get_options().transitive
    if self.is_internal_only and self.is_external_only:
      raise TaskError('At most one of --internal-only or --external-only can be selected.')

  def console_output(self, unused_method_argument):
    for target in self.context.target_roots:
      ordered_closure = OrderedSet()
      if self._transitive:
        target.walk(ordered_closure.add)
      else:
        ordered_closure.update(target.dependencies)
      for tgt in ordered_closure:
        if not self.is_external_only:
          yield tgt.address.spec
        if not self.is_internal_only:
          # TODO(John Sirois): We need an external payload abstraction at which point knowledge
          # of jar and requirement payloads can go and this hairball will be untangled.
          if isinstance(tgt.payload.get_field('requirements'), PythonRequirementsField):
            for requirement in tgt.payload.requirements:
              yield str(requirement.requirement)
          elif isinstance(tgt.payload.get_field('jars'), JarsField):
            for jar in tgt.payload.jars:
              data = dict(org=jar.org, name=jar.name, rev=jar.rev)
              yield ('{org}:{name}:{rev}' if jar.rev else '{org}:{name}').format(**data)
