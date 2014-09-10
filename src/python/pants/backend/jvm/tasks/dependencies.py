# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError
from pants.base.payload_field import JarsField, PythonRequirementsField


# XXX(pl): JVM/Python hairball violator
class Dependencies(ConsoleTask):
  """Generates a textual list (using the target format) for the dependency set of a target."""

  @staticmethod
  def _is_jvm(target):
    return target.is_jvm or target.is_jvm_app

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(Dependencies, cls).setup_parser(option_group, args, mkflag)

    cls.internal_only_flag = mkflag("internal-only")
    cls.external_only_flag = mkflag("external-only")

    option_group.add_option(cls.internal_only_flag,
                            action="store_true",
                            dest="dependencies_is_internal_only",
                            default=False,
                            help='Specifies that only internal dependencies should'
                                 ' be included in the graph output (no external jars).')
    option_group.add_option(cls.external_only_flag,
                            action="store_true",
                            dest="dependencies_is_external_only",
                            default=False,
                            help='Specifies that only external dependencies should'
                                 ' be included in the graph output (only external jars).')

  def __init__(self, *args, **kwargs):
    super(Dependencies, self).__init__(*args, **kwargs)

    if (self.context.options.dependencies_is_internal_only and
        self.context.options.dependencies_is_external_only):

      error_str = "At most one of %s or %s can be selected." % (self.internal_only_flag,
                                                                self.external_only_flag)
      raise TaskError(error_str)

    self.is_internal_only = self.context.options.dependencies_is_internal_only
    self.is_external_only = self.context.options.dependencies_is_external_only

  def console_output(self, unused_method_argument):
    for target in self.context.target_roots:
      ordered_closure = OrderedSet()
      target.walk(ordered_closure.add)
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
