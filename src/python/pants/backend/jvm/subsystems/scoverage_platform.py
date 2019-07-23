# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pants.build_graph.injectables_mixin import InjectablesMixin
from pants.subsystem.subsystem import Subsystem
from pants.java.jar.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.address import Address
from typing import Any, Dict, List, Optional, Union


SCOVERAGE = "scoverage"
blacklist_file = 'new_blacklist_scoverage'


class ScoveragePlatform(InjectablesMixin, Subsystem):
  """The scala coverage platform."""

  options_scope = 'scoverage'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--enable-scoverage',
      default=False,
      type=bool,
      help='Specifies whether to generate scoverage reports for scala test targets.'
           'Default value is False. If True,'
           'implies --test-junit-coverage-processor=scoverage.')

    register('--blacklist-file',
      default=blacklist_file,
      type=str,
      help='Path to files containing targets not to be instrumented.')

    register('--scoverage-target-path',
      default='//:scoverage',
      type=str,
      help='Path to the scoverage dependency.')

  def scoverage_jar(self):
    return [JarDependency(org='com.twitter.scoverage', name='scalac-scoverage-plugin_2.12',
      rev='1.0.1-twitter'),
      JarDependency(org='com.twitter.scoverage', name='scalac-scoverage-runtime_2.12',
        rev='1.0.1-twitter')]

  def injectables(self, build_graph):
    specs_to_create = [
      ('scoverage', self.scoverage_jar),
    ]

    for spec_key, create_jardep_func in specs_to_create:
      spec = self.injectables_spec_for_key(spec_key)
      target_address = Address.parse(spec)
      if not build_graph.contains_address(target_address):
        target_jars = create_jardep_func()
        jars = target_jars if isinstance(target_jars, list) else [target_jars]
        build_graph.inject_synthetic_target(target_address,
          JarLibrary,
          jars=jars,
          scope='forced')
      elif not build_graph.get_target(target_address).is_synthetic:
        raise build_graph.ManualSyntheticTargetError(target_address)

  @property
  def injectables_spec_mapping(self):
    return {
      'scoverage': [f"{self.get_options().scoverage_target_path}"],
    }


  def is_blacklisted(self, target) -> bool:
    """
    Checks if the [target] is blacklisted or not.
    """
    if not os.path.exists(self.get_options().blacklist_file):
      return False

    if target.address.spec in open(self.get_options().blacklist_file).read():
      return True
    else:
      return False
