# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import importlib
import traceback

from pkg_resources import Requirement
from twitter.common.collections import OrderedSet

from pants.base.exceptions import BackendConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration


class PluginLoadingError(Exception): pass


class PluginNotFound(PluginLoadingError): pass


class PluginLoadOrderError(PluginLoadingError): pass


def load_plugins_and_backends(plugins, working_set, backends):
  """Load named plugins and source backends

  :param list<str> plugins: Plugins to load (see `load_plugins`).
  :param WorkingSet working_set: A pkg_resources.WorkingSet to load plugins from.
  :param list<str> backends: Source backends to load (see `load_build_configuration_from_source`).
  """
  build_configuration = BuildConfiguration()
  load_plugins(build_configuration, plugins or [], working_set)
  load_build_configuration_from_source(build_configuration, additional_backends=backends or [])
  return build_configuration


def load_plugins(build_configuration, plugins, working_set):
  """Load named plugins from the current working_set into the supplied build_configuration

  "Loading" a plugin here refers to calling registration methods -- it is assumed each plugin
  is already on the path and an error will be thrown if it is not. Plugins should define their
  entrypoints in the `pantsbuild.plugin` group when configuring their distribution.

  Like source backends, the `build_file_aliases`, `global_subsystems` and `register_goals` methods
  are called if those entry points are defined.

  * Plugins are loaded in the order they are provided. *

  This is important as loading can add, remove or replace exiting tasks installed by other plugins.

  If a plugin needs to assert that another plugin is registered before it, it can define an
  entrypoint "load_after" which can return a list of plugins which must have been loaded before it
  can be loaded. This does not change the order or what plugins are loaded in any way -- it is
  purely an assertion to guard against misconfiguration.

  :param BuildConfiguration build_configuration: The BuildConfiguration (for adding aliases).
  :param list<str> plugins: A list of plugin names optionally with versions, in requirement format.
                            eg ['widgetpublish', 'widgetgen==1.2'].
  :param WorkingSet working_set: A pkg_resources.WorkingSet to load plugins from.
  """
  loaded = {}
  for plugin in plugins:
    req = Requirement.parse(plugin)
    dist = working_set.find(req)

    if not dist:
      raise PluginNotFound('Could not find plugin: {}'.format(req))

    entries = dist.get_entry_map().get('pantsbuild.plugin', {})

    if 'load_after' in entries:
      deps = entries['load_after'].load()()
      for dep_name in deps:
        dep = Requirement.parse(dep_name)
        if dep.key not in loaded:
          raise PluginLoadOrderError('Plugin {0} must be loaded after {1}'.format(plugin, dep))

    if 'build_file_aliases' in entries:
      aliases = entries['build_file_aliases'].load()()
      build_configuration.register_aliases(aliases)

    if 'register_goals' in entries:
      entries['register_goals'].load()()

    if 'global_subsystems' in entries:
      subsystems = entries['global_subsystems'].load()()
      build_configuration.register_subsystems(subsystems)

    loaded[dist.as_requirement().key] = dist


def load_build_configuration_from_source(build_configuration, additional_backends=None):
  """Installs pants backend packages to provide targets and helper functions to BUILD files and
  goals to the cli.

  :param BuildConfiguration build_configuration: The BuildConfiguration (for adding aliases).
  :param additional_backends: An optional list of additional packages to load backends from.
  :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
    the build configuration.
  """
  backend_packages = ['pants.backend.authentication',
                      'pants.backend.core',
                      'pants.backend.python',
                      'pants.backend.jvm',
                      'pants.backend.codegen',
                      'pants.backend.maven_layout',
                      'pants.backend.project_info']

  for backend_package in OrderedSet(backend_packages + (additional_backends or [])):
    load_backend(build_configuration, backend_package)


def load_backend(build_configuration, backend_package):
  """Installs the given backend package into the build configuration.

  :param build_configuration the :class:``pants.build_graph.build_configuration.BuildConfiguration`` to
    install the backend plugin into.
  :param string backend_package: the package name containing the backend plugin register module that
    provides the plugin entrypoints.
  :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
    the build configuration."""
  backend_module = backend_package + '.register'
  try:
    module = importlib.import_module(backend_module)
  except ImportError as e:
    traceback.print_exc()
    raise BackendConfigurationError('Failed to load the {backend} backend: {error}'
                                    .format(backend=backend_module, error=e))

  def invoke_entrypoint(name):
    entrypoint = getattr(module, name, lambda: None)
    try:
      return entrypoint()
    except TypeError as e:
      traceback.print_exc()
      raise BackendConfigurationError(
          'Entrypoint {entrypoint} in {backend} must be a zero-arg callable: {error}'
          .format(entrypoint=name, backend=backend_module, error=e))

  build_file_aliases = invoke_entrypoint('build_file_aliases')
  if build_file_aliases:
    build_configuration.register_aliases(build_file_aliases)

  subsystems = invoke_entrypoint('global_subsystems')
  if subsystems:
    build_configuration.register_subsystems(subsystems)

  invoke_entrypoint('register_goals')
