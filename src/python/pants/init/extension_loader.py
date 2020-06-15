# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import traceback
from typing import Dict, List, Optional

from pkg_resources import Requirement, WorkingSet

from pants.base.exceptions import BackendConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.util.ordered_set import FrozenOrderedSet


class PluginLoadingError(Exception):
    pass


class PluginNotFound(PluginLoadingError):
    pass


class PluginLoadOrderError(PluginLoadingError):
    pass


def load_backends_and_plugins(
    plugins1: List[str],
    plugins2: List[str],
    working_set: WorkingSet,
    backends1: List[str],
    backends2: List[str],
    bc_builder: Optional[BuildConfiguration.Builder] = None,
) -> BuildConfiguration:
    """Load named plugins and source backends.

    :param plugins1: v1 plugins to load.
    :param plugins2: v2 plugins to load.
    :param working_set: A pkg_resources.WorkingSet to load plugins from.
    :param backends1: v1 backends to load.
    :param backends2: v2 backends to load.
    :param bc_builder: The BuildConfiguration (for adding aliases).
    """
    bc_builder = bc_builder or BuildConfiguration.Builder()
    load_build_configuration_from_source(bc_builder, backends1, backends2)
    load_plugins(bc_builder, plugins1, working_set, is_v1_plugin=True)
    load_plugins(bc_builder, plugins2, working_set, is_v1_plugin=False)
    return bc_builder.create()


def load_plugins(
    build_configuration: BuildConfiguration.Builder,
    plugins: List[str],
    working_set: WorkingSet,
    is_v1_plugin: bool,
) -> None:
    """Load named plugins from the current working_set into the supplied build_configuration.

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

    :param build_configuration: The BuildConfiguration (for adding aliases).
    :param plugins: A list of plugin names optionally with versions, in requirement format.
                              eg ['widgetpublish', 'widgetgen==1.2'].
    :param working_set: A pkg_resources.WorkingSet to load plugins from.
    :param is_v1_plugin: Whether this is a v1 or v2 plugin.
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

        # While the Target API is a V2 concept, we expect V1 plugin authors to still write Target
        # API bindings. So, we end up using this entry point regardless of V1 vs. V2.
        #
        # We also always load `build_file_aliases` because mixed repositories need to write V1
        # bindings for targets to avoid breaking V1-only goals; and there is no V2 entry-point for
        # `objects` yet. Purely V2-repos can ignore `build_file_aliases`.
        if "target_types" in entries:
            target_types = entries["target_types"].load()()
            build_configuration.register_target_types(target_types)
        if "build_file_aliases" in entries:
            aliases = entries["build_file_aliases"].load()()
            build_configuration.register_aliases(aliases)

        if is_v1_plugin:
            if "register_goals" in entries:
                entries["register_goals"].load()()
            if "global_subsystems" in entries:
                subsystems = entries["global_subsystems"].load()()
                build_configuration.register_optionables(subsystems)
        else:
            if "rules" in entries:
                rules = entries["rules"].load()()
                build_configuration.register_rules(rules)
        loaded[dist.as_requirement().key] = dist


def load_build_configuration_from_source(
    build_configuration: BuildConfiguration.Builder, backends1: List[str], backends2: List[str]
) -> None:
    """Installs pants backend packages to provide BUILD file symbols and cli goals.

    :param build_configuration: The BuildConfiguration (for adding aliases).
    :param backends1: An list of packages to load v1 backends from.
    :param backends2: An list of packages to load v2 backends from.
    :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
      the build configuration.
    """
    # pants.build_graph and pants.core_task must always be loaded, and before any other backends.
    backend_packages1 = FrozenOrderedSet(["pants.build_graph", "pants.core_tasks", *backends1])
    for backend_package in backend_packages1:
        load_backend(build_configuration, backend_package, is_v1_backend=True)

    backend_packages2 = FrozenOrderedSet(
        ["pants.core", "pants.backend.pants_info", "pants.backend.project_info", *backends2]
    )
    for backend_package in backend_packages2:
        load_backend(build_configuration, backend_package, is_v1_backend=False)


def load_backend(
    build_configuration: BuildConfiguration.Builder, backend_package: str, is_v1_backend: bool
) -> None:
    """Installs the given backend package into the build configuration.

    :param build_configuration: the BuildConfiguration to install the backend plugin into.
    :param backend_package: the package name containing the backend plugin register module that
      provides the plugin entrypoints.
    :param is_v1_backend: Is this a v1 or v2 backend.
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

    # See the comment in `load_plugins` for why we load both `target_types` and
    # `build_file_aliases` in both V1 and V2.
    target_types = invoke_entrypoint("target_types")
    if target_types:
        build_configuration.register_target_types(target_types)
    build_file_aliases = invoke_entrypoint("build_file_aliases")
    if build_file_aliases:
        build_configuration.register_aliases(build_file_aliases)

    if is_v1_backend:
        invoke_entrypoint("register_goals")
        subsystems = invoke_entrypoint("global_subsystems")
        if subsystems:
            build_configuration.register_optionables(subsystems)
    else:
        rules = invoke_entrypoint("rules")
        if rules:
            build_configuration.register_rules(rules)
