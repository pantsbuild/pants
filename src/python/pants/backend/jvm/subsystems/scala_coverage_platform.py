# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.build_graph.injectables_mixin import InjectablesMixin
from pants.subsystem.subsystem import Subsystem


SCOVERAGE = "scoverage"
blacklist_file = 'new_blacklist_scoverage'


class ScalaCoveragePlatform(InjectablesMixin, Subsystem):
  """The scala coverage platform."""

  options_scope = 'scala-coverage'

  @classmethod
  def register_options(cls, register):
    super(ScalaCoveragePlatform, cls).register_options(register)
    register('--enable-scoverage',
      default=False,
      type=bool,
      help='Specifies whether to generate scoverage reports for scala test targets.'
           'Default value is False')

    register('--scoverage-target-path',
      default='//:scoverage',
      type=str,
      help='Path to the scoverage dependency.')

  @property
  def injectables_spec_mapping(self):
    return {
      'scoverage': ['{}'.format(self.get_options().scoverage_target_path)],
    }

  def get_scalac_plugins(self, target):
    """
    Adds 'scoverage' to scalac_plugins in case scoverage is enabled for that [target].
    :return: modified scalac_plugins
    :rtype: list of strings
    """

    # Prevent instrumenting generated targets and targets in blacklist.
    if target.identifier.startswith(".pants.d.gen") or self.is_blacklisted(target):
      return target.payload.scalac_plugins

    scalac_plugins = target.payload.scalac_plugins
    if scalac_plugins:
      scalac_plugins.append(SCOVERAGE)
    else:
      scalac_plugins = [SCOVERAGE]
    return scalac_plugins

  def get_scalac_plugin_args(self, target):
    """
    Adds 'scoverage' to scalac_plugins_args in case scoverage is enabled for that [target].
    :return: modified scalac_plugins_args
    :rtype: map from string to list of strings.
    """
    scalac_plugin_args = target.payload.scalac_plugin_args
    if scalac_plugin_args:
      scalac_plugin_args.update(
        {"scoverage": ["writeToClasspath:true", "dataDir:{}".format(target.identifier)]})
    else:
      scalac_plugin_args = {
        "scoverage": ["writeToClasspath:true", "dataDir:{}".format(target.identifier)]
      }
    return scalac_plugin_args

  def get_compiler_option_sets(self, target):
    """
   Adds 'scoverage' to compiler_options_sets in case scoverage is enabled for that [target].
   :return: modified compiler_option_sets
   :rtype: see constructor
   """
    compiler_option_sets = target.payload.compiler_option_sets
    if compiler_option_sets:
      list(compiler_option_sets).append(SCOVERAGE)
    else:
      compiler_option_sets = [SCOVERAGE]
    return tuple(compiler_option_sets)

  def is_blacklisted(self, target):
    """
    Checks if the [target] is blacklisted or not.
    """
    if target.address.spec in open(blacklist_file).read():
      return True
    else:
      return False
