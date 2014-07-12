# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.base.build_configuration import BuildConfiguration


def load_build_configuration_from_source(additional_backends=None):
  """Installs pants backend packages to provide targets and helper functions to BUILD files and
  goals to the cli.

  :param additional_backends: An optional list of additional packages to load backends from.
  :returns: a new :class:``pants.base.build_configuration.BuildConfiguration``
  """
  build_configuration = BuildConfiguration()
  backend_packages = ['pants.backend.core',
                      'pants.backend.python',
                      'pants.backend.jvm',
                      'pants.backend.codegen',
                      'pants.backend.maven_layout',
                      'pants.backend.android']

  for backend_package in OrderedSet(backend_packages + (additional_backends or [])):
    module = __import__(backend_package + '.register',
                        {},  # globals
                        {},  # locals
                        ['build_file_aliases',
                         'register_commands',
                         'register_goals'])

    build_file_aliases = module.build_file_aliases()
    build_configuration.register_aliases(build_file_aliases)

    module.register_commands()
    module.register_goals()

  return build_configuration
