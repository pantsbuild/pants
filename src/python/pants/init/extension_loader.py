# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import traceback

from pkg_resources import Requirement
from twitter.common.collections import OrderedSet

from pants.base.exceptions import BackendConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration


class PluginLoadingError(Exception): pass


class PluginNotFound(PluginLoadingError): pass


class PluginLoadOrderError(PluginLoadingError): pass


def load_backends_and_plugins(plugins, working_set, backends, build_configuration, v1_register):
  """Load named plugins and source backends

  :param list<str> plugins: Plugins to load (see `load_plugins`).  Plugins are loaded after
    backends.
  :param WorkingSet working_set: A pkg_resources.WorkingSet to load plugins from.
  :param list<str> backends: Source backends to load (see `load_build_configuration_from_source`).
  :param BuildConfiguration build_configuration: The BuildConfiguration (for adding aliases).
  :param bool v1_register: Whether to register v1 tasks.
  """
  load_build_configuration_from_source(build_configuration, backends, v1_register)
  load_plugins(build_configuration, plugins or [], working_set, v1_register)
  return build_configuration


def load_plugins(build_configuration, plugins, working_set, v1_register):
  """Load named plugins from the current working_set into the supplied build_configuration

  "Loading" a plugin here refers to calling registration methods -- it is assumed each plugin
  is already on the path and an error will be thrown if it is not. Plugins should define their
  entrypoints in the `pantsbuild.plugin` group when configuring their distribution.

  Like source backends, the `build_file_aliases`, `global_subsystems` and `register_goals` methods
  are called if those entry points are defined.

  * Plugins are loaded in the order they are provided. *

  This is important as loading can add, remove or replace existing tasks installed by other plugins.

  If a plugin needs to assert that another plugin is registered before it, it can define an
  entrypoint "load_after" which can return a list of plugins which must have been loaded before it
  can be loaded. This does not change the order or what plugins are loaded in any way -- it is
  purely an assertion to guard against misconfiguration.

  :param BuildConfiguration build_configuration: The BuildConfiguration (for adding aliases).
  :param list<str> plugins: A list of plugin names optionally with versions, in requirement format.
                            eg ['widgetpublish', 'widgetgen==1.2'].
  :param WorkingSet working_set: A pkg_resources.WorkingSet to load plugins from.
  :param bool v1_register: Whether to register v1 tasks.
  """
  loaded = {}
  for plugin in plugins:
    req = Requirement.parse(plugin)
    dist = working_set.find(req)

    if not dist:
      raise PluginNotFound(f'Could not find plugin: {req}')

    entries = dist.get_entry_map().get('pantsbuild.plugin', {})

    if v1_register:
      # TODO: Might v2 plugins care about registration order? Hopefully not.
      if 'load_after' in entries:
        deps = entries['load_after'].load()()
        for dep_name in deps:
          dep = Requirement.parse(dep_name)
          if dep.key not in loaded:
            raise PluginLoadOrderError(f'Plugin {plugin} must be loaded after {dep}')

      if 'register_goals' in entries:
        entries['register_goals'].load()()

      # TODO: Might v2 plugins need to register global subsystems? Hopefully not.
      if 'global_subsystems' in entries:
        subsystems = entries['global_subsystems'].load()()
        build_configuration.register_optionables(subsystems)

    if 'build_file_aliases' in entries:
      aliases = entries['build_file_aliases'].load()()
      build_configuration.register_aliases(aliases)

    if 'rules' in entries:
      rules = entries['rules'].load()()
      build_configuration.register_rules(rules)

    loaded[dist.as_requirement().key] = dist


def load_build_configuration_from_source(build_configuration, backends, v1_register):
  """Installs pants backend packages to provide BUILD file symbols and cli goals.

  :param BuildConfiguration build_configuration: The BuildConfiguration (for adding aliases).
  :param backends: An list of packages to load backends from.
  :param v1_register: Whether to register v1 tasks.
  :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
    the build configuration.
  """
  # pants.build_graph and pants.core_task must always be loaded, and before any other backends.
  # TODO: Consider replacing the "backend" nomenclature here. pants.build_graph and
  # pants.core_tasks aren't really backends.
  backend_packages = OrderedSet([
      'pants.build_graph',
      'pants.core_tasks',
      'pants.rules.core',
    ] + (backends or []))
  for backend_package in backend_packages:
    load_backend(build_configuration, backend_package, v1_register)


def load_backend(build_configuration: BuildConfiguration, backend_package: str,
                 v1_register: bool) -> None:
  """Installs the given backend package into the build configuration.

  :param build_configuration: the BuildConfiguration to install the backend plugin into.
  :param backend_package: the package name containing the backend plugin register module that
    provides the plugin entrypoints.
  :param bool v1_register: Whether to register v1 tasks.
  :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
    the build configuration."""
  backend_module = backend_package + '.register'
  try:
    module = importlib.import_module(backend_module)
  except ImportError as ex:
    traceback.print_exc()
    raise BackendConfigurationError(f'Failed to load the {backend_module} backend: {ex!r}')

  def invoke_entrypoint(name):
    entrypoint = getattr(module, name, lambda: None)
    try:
      return entrypoint()
    except TypeError as e:
      traceback.print_exc()
      raise BackendConfigurationError(
        f'Entrypoint {name} in {backend_module} must be a zero-arg callable: {e!r}'
      )

  if v1_register:
    invoke_entrypoint('register_goals')

    # TODO: Might v2 plugins need to register global subsystems? Hopefully not.
    subsystems = invoke_entrypoint('global_subsystems')
    if subsystems:
      build_configuration.register_optionables(subsystems)

  build_file_aliases = invoke_entrypoint('build_file_aliases')
  if build_file_aliases:
    build_configuration.register_aliases(build_file_aliases)

  rules = invoke_entrypoint('rules')
  if rules:
    build_configuration.register_rules(rules)
