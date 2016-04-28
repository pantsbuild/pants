# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.address import Address
from pants.option.custom_types import target_option
from pants.subsystem.subsystem import Subsystem


class JavacPluginSetup(Subsystem):
  """Java compiler plugin setup.

  Establishes a global classpath to find javac plugins on (in addition to the dependencies of the
  targets being compiled).  Which plugins to actually activate in a given compile, and with which
  args, is determined by the --javac-plugins and --javac-plugins-args options on compile.zinc.
  """
  options_scope = 'javac-plugin-setup'

  @classmethod
  def register_options(cls, register):
    register('--deps', advanced=True, type=list, member_type=target_option,
             fingerprint=True,
             help='Requested javac plugins will be found in these targets, as well as in any '
                  'dependencies of the targets being compiled.')

  @classmethod
  def global_plugin_dependency_specs(cls):
    # TODO: This check is a hack to allow tests to pass without having to set up subsystems.
    # We have hundreds of tests that use JvmTargets, either as a core part of the test, or
    # incidentally when testing build graph functionality, and it would be onerous to make them
    # all set up a subsystem they don't care about.
    if cls.has_options():
      return cls.global_instance().plugin_dependency_specs()
    else:
      return []

  def __init__(self, *args, **kwargs):
    super(JavacPluginSetup, self).__init__(*args, **kwargs)
    # Parse the specs in order to normalize them, so we can do string comparisons on them.
    opts = self.get_options()
    # TODO: This check is a continuation of the hack that allows tests to pass without caring
    # about this subsystem.
    if hasattr(opts, 'deps'):
      self._dependency_specs = [Address.parse(spec).spec for spec in self.get_options().deps]
    else:
      self._dependency_specs = []

  def plugin_dependency_specs(self):
    return self._dependency_specs
