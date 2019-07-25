# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from pants.build_graph.injectables_mixin import InjectablesMixin
from pants.subsystem.subsystem import Subsystem
from pants.java.jar.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.address import Address

logger = logging.getLogger(__name__)

SCOVERAGE = "scoverage"

class ScoveragePlatform(InjectablesMixin, Subsystem):
  """The scoverage platform."""

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
      type=str,
      help='Path to files containing targets not to be instrumented.')

    register('--scoverage-target-path',
      default='//:scoverage',
      type=str,
      help='Path to the scoverage dependency.')

  def __init__(self, *args, **kwargs):
    super(ScoveragePlatform, self).__init__(*args, **kwargs)

    # Setting up the scoverage blacklist files which contains targets
    # not to be instrumented. Since the file is not expected to be really big,
    # would it be ok to store it in memory?
    if (self.get_options().blacklist_file and
      os.path.exists(self.get_options().blacklist_file)):
      self._blacklist_file_contents = open(self.get_options().blacklist_file).read()
    else:
      self._blacklist_file_contents = None

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
    # File not specified
    if not self._blacklist_file_contents:
      return False

    if target.address.spec in self._blacklist_file_contents:
      logger.warning(f"{target.address.spec} found in blacklist, not instrumented.")
      return True
    else:
      return False
