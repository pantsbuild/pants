# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet

from pants.base.build_configuration import BuildConfiguration
from pants.base.exceptions import BackendConfigurationError


def load_build_configuration_from_source(additional_backends=None):
  """Installs pants backend packages to provide targets and helper functions to BUILD files and
  goals to the cli.

  :param additional_backends: An optional list of additional packages to load backends from.
  :returns: a new :class:``pants.base.build_configuration.BuildConfiguration``.
  :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
    the build configuration.
  """
  build_configuration = BuildConfiguration()
  backend_packages = ['pants.backend.authentication',
                      'pants.backend.core',
                      'pants.backend.python',
                      'pants.backend.jvm',
                      'pants.backend.codegen',
                      'pants.backend.maven_layout',
                      'pants.backend.android']

  for backend_package in OrderedSet(backend_packages + (additional_backends or [])):
    load_backend(build_configuration, backend_package)

  return build_configuration


def load_backend(build_configuration, backend_package):
  """Installs the given backend package into the build configuration.

  :param build_configuration the :class:``pants.base.build_configuration.BuildConfiguration`` to
    install the backend plugin into.
  :param string backend_package: the package name containing the backend plugin register module that
    provides the plugin entrypoints.
  :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
    the build configuration."""
  backend_module = backend_package + '.register'
  try:
    module = __import__(backend_module,
                        {},  # globals
                        {},  # locals
                        ['build_file_aliases',
                         'register_commands',
                         'register_goals'])
  except ImportError as e:
    raise BackendConfigurationError('Failed to load the {backend} backend: {error}'
                                    .format(backend=backend_module, error=e))

  def invoke_entrypoint(name):
    entrypoint = getattr(module, name, lambda: None)
    try:
      return entrypoint()
    except TypeError as e:
      raise BackendConfigurationError(
          'Entrypoint {entrypoint} in {backend} must be a zero-arg callable: {error}'
          .format(entrypoint=name, backend=backend_module, error=e))

  build_file_aliases = invoke_entrypoint('build_file_aliases')
  if build_file_aliases:
    build_configuration.register_aliases(build_file_aliases)

  invoke_entrypoint('register_commands')
  invoke_entrypoint('register_goals')
