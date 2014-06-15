# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet


def load_backends_from_source(build_file_parser, additional_backends=None):
  """Installs pants backend packages to provide targets and helper functions to BUILD files and
  goals to the cli.

  :param build_file_parser: The parser to populate with target aliases and helper functions from
    the backends.
  :param additional_backends: An optional list of additional packages to load backends from.
  """
  backend_packages = [
    'pants.backend.core',
    'pants.backend.python',
    'pants.backend.jvm',
    'pants.backend.codegen',
    'pants.backend.maven_layout',
  ]
  for backend_package in OrderedSet(backend_packages + (additional_backends or [])):
    module = __import__(backend_package + '.register',
                        {},  # globals
                        {},  # locals
                        [
                          'target_aliases',
                          'object_aliases',
                          'applicative_path_relative_util_aliases',
                          'partial_path_relative_util_aliases',
                          'target_creation_utils',
                          'commands',
                          'goals',
                        ])
    #TODO (tdesai) ISSUE-191 Consolidate all the 5 in two extension points.
    for alias, target_type in module.target_aliases().items():
      build_file_parser.register_target_alias(alias, target_type)

    for alias, obj in module.object_aliases().items():
      build_file_parser.register_exposed_object(alias, obj)

    for alias, util in module.applicative_path_relative_util_aliases().items():
      build_file_parser.register_applicative_path_relative_util(alias, util)

    for alias, util in module.partial_path_relative_util_aliases().items():
      build_file_parser.register_partial_path_relative_util(alias, util)

    for alias, func in module.target_creation_utils().items():
      build_file_parser.register_target_creation_utils(alias, func)

    module.register_commands()
    module.register_goals()
