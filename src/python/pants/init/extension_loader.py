# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import traceback
from typing import Dict, List, Optional

from pkg_resources import Requirement, WorkingSet

from pants.base.exceptions import BackendConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.goal.builtins import register_builtin_goals
from pants.util.ordered_set import FrozenOrderedSet


class PluginLoadingError(Exception):
    pass


class PluginNotFound(PluginLoadingError):
    pass


class PluginLoadOrderError(PluginLoadingError):
    pass


def load_backends_and_plugins(
    plugins: List[str],
    working_set: WorkingSet,
    backends: List[str],
    bc_builder: Optional[BuildConfiguration.Builder] = None,
) -> BuildConfiguration:
    """Load named plugins and source backends.

    :param plugins: v2 plugins to load.
    :param working_set: A pkg_resources.WorkingSet to load plugins from.
    :param backends: v2 backends to load.
    :param bc_builder: The BuildConfiguration (for adding aliases).
    """
    bc_builder = bc_builder or BuildConfiguration.Builder()
    load_build_configuration_from_source(bc_builder, backends)
    load_plugins(bc_builder, plugins, working_set)
    register_builtin_goals(bc_builder)
    return bc_builder.create()


def load_plugins(
    build_configuration: BuildConfiguration.Builder,
    plugins: List[str],
    working_set: WorkingSet,
) -> None:
    """Load named plugins from the current working_set into the supplied build_configuration.

    "Loading" a plugin here refers to calling registration methods -- it is assumed each plugin
    is already on the path and an error will be thrown if it is not. Plugins should define their
    entrypoints in the `pantsbuild.plugin` group when configuring their distribution.

    Like source backends, the `build_file_aliases`, and `register_goals` methods are called if
    those entry points are defined.

    * Plugins are loaded in the order they are provided. *

    This is important as loading can add, remove or replace existing tasks installed by other plugins.

    If a plugin needs to assert that another plugin is registered before it, it can define an
    entrypoint "load_after" which can return a list of plugins which must have been loaded before it
    can be loaded. This does not change the order or what plugins are loaded in any way -- it is
    purely an assertion to guard against misconfiguration.

    :param build_configuration: The BuildConfiguration (for adding aliases).
    :param plugins: A list of plugin names optionally with versions, in requirement format.
                              eg ['widgetpublish', 'widgetgen==1.2'].
    :param working_set: A pkg_resources.WorkingSet to load plugins from.
    """
    loaded: Dict = {}
    for plugin in plugins or []:
        req = Requirement.parse(plugin)
        dist = working_set.find(req)

        if not dist:
            raise PluginNotFound(f"Could not find plugin: {req}")

        entries = dist.get_entry_map().get("pantsbuild.plugin", {})

        if "load_after" in entries:
            deps = entries["load_after"].load()()
            for dep_name in deps:
                dep = Requirement.parse(dep_name)
                if dep.key not in loaded:
                    raise PluginLoadOrderError(f"Plugin {plugin} must be loaded after {dep}")
        if "target_types" in entries:
            target_types = entries["target_types"].load()()
            build_configuration.register_target_types(req.key, target_types)
        if "build_file_aliases" in entries:
            aliases = entries["build_file_aliases"].load()()
            build_configuration.register_aliases(aliases)
        if "rules" in entries:
            rules = entries["rules"].load()()
            build_configuration.register_rules(req.key, rules)
        loaded[dist.as_requirement().key] = dist


def load_build_configuration_from_source(
    build_configuration: BuildConfiguration.Builder, backends: List[str]
) -> None:
    """Installs pants backend packages to provide BUILD file symbols and cli goals.

    :param build_configuration: The BuildConfiguration (for adding aliases).
    :param backends: An list of packages to load v2 backends from.
    :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
      the build configuration.
    """
    backend_packages = FrozenOrderedSet(["pants.core", "pants.backend.project_info", *backends])
    for backend_package in backend_packages:
        load_backend(build_configuration, backend_package)


def load_backend(build_configuration: BuildConfiguration.Builder, backend_package: str) -> None:
    """Installs the given backend package into the build configuration.

    :param build_configuration: the BuildConfiguration to install the backend plugin into.
    :param backend_package: the package name containing the backend plugin register module that
      provides the plugin entrypoints.
    :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
      the build configuration.
    """
    backend_module = backend_package + ".register"
    try:
        module = importlib.import_module(backend_module)
    except ImportError as ex:
        traceback.print_exc()
        raise BackendConfigurationError(f"Failed to load the {backend_module} backend: {ex!r}")

    def invoke_entrypoint(name):
        entrypoint = getattr(module, name, lambda: None)
        try:
            return entrypoint()
        except TypeError as e:
            traceback.print_exc()
            raise BackendConfigurationError(
                f"Entrypoint {name} in {backend_module} must be a zero-arg callable: {e!r}"
            )

    target_types = invoke_entrypoint("target_types")
    if target_types:
        build_configuration.register_target_types(backend_package, target_types)
    build_file_aliases = invoke_entrypoint("build_file_aliases")
    if build_file_aliases:
        build_configuration.register_aliases(build_file_aliases)
    rules = invoke_entrypoint("rules")
    if rules:
        build_configuration.register_rules(backend_package, rules)
