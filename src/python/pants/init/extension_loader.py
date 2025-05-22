# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import logging
import traceback
from collections.abc import Callable, Iterable
from typing import Any

from pkg_resources import EntryPoint, Requirement, WorkingSet

from pants.base.exceptions import BackendConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.goal.auxiliary_goal import AuxiliaryGoal
from pants.goal.builtins import register_builtin_goals
from pants.init.extension_api import ExtensionInitContextV0
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


_EXTENSION_INITIALIZE_METHOD_NAME = "initializeV0"


class PluginLoadingError(Exception):
    pass


class PluginNotFound(PluginLoadingError):
    pass


class PluginLoadOrderError(PluginLoadingError):
    pass


class PluginExtensionInitContext(ExtensionInitContextV0):
    def __init__(self, key: str, build_configuration: BuildConfiguration.Builder):
        self._key = key
        self._build_configuration = build_configuration

    def register_aliases(self, aliases: BuildFileAliases) -> None:
        self._build_configuration.register_aliases(aliases)

    def register_auxiliary_goals(self, goals: Iterable[type[AuxiliaryGoal]]) -> None:
        self._build_configuration.register_auxiliary_goals(self._key, goals)

    def register_remote_auth_plugin(self, remote_auth_plugin: Callable) -> None:
        self._build_configuration.register_remote_auth_plugin(remote_auth_plugin)

    def register_rules(self, rules: Iterable[Rule | UnionRule]) -> None:
        self._build_configuration.register_rules(self._key, rules)

    def register_subsystems(self, subsystems: Iterable[type[Subsystem]]) -> None:
        self._build_configuration.register_subsystems(self._key, subsystems)

    def register_target_types(self, target_types: Iterable[type[Target]] | Any) -> None:
        self._build_configuration.register_target_types(self._key, target_types)


def load_backends_and_plugins(
    plugins: list[str],
    working_set: WorkingSet,
    backends: list[str],
    bc_builder: BuildConfiguration.Builder | None = None,
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


def _legacy_extension_init(
    plugin_name: str,
    key: str,
    entries: dict[str, EntryPoint],
    build_configuration: BuildConfiguration.Builder,
    loaded: dict[str, Any],
) -> None:
    if "load_after" in entries:
        deps = entries["load_after"].load()()
        for dep_name in deps:
            dep = Requirement.parse(dep_name)
            if dep.key not in loaded:
                raise PluginLoadOrderError(f"Plugin {plugin_name} must be loaded after {dep}")
    if "target_types" in entries:
        target_types = entries["target_types"].load()()
        build_configuration.register_target_types(key, target_types)
    if "build_file_aliases" in entries:
        aliases = entries["build_file_aliases"].load()()
        build_configuration.register_aliases(aliases)
    if "rules" in entries:
        rules = entries["rules"].load()()
        build_configuration.register_rules(key, rules)
    if "remote_auth" in entries:
        remote_auth_func = entries["remote_auth"].load()
        logger.debug(
            f"register remote auth function {remote_auth_func.__module__}.{remote_auth_func.__name__} from plugin: {plugin_name}"
        )
        build_configuration.register_remote_auth_plugin(remote_auth_func)
    if "auxiliary_goals" in entries:
        auxiliary_goals = entries["auxiliary_goals"].load()()
        build_configuration.register_auxiliary_goals(key, auxiliary_goals)


def load_plugins(
    build_configuration: BuildConfiguration.Builder,
    plugins: list[str],
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
    loaded: dict = {}
    for plugin in plugins or []:
        req = Requirement.parse(plugin)
        dist = working_set.find(req)

        if not dist:
            raise PluginNotFound(f"Could not find plugin: {req}")

        entries = dist.get_entry_map().get("pantsbuild.plugin", {})

        if _EXTENSION_INITIALIZE_METHOD_NAME in entries:
            initializer = entries[_EXTENSION_INITIALIZE_METHOD_NAME].load()
            initializer_context = PluginExtensionInitContext(
                key=req.key, build_configuration=build_configuration
            )
            try:
                initializer(initializer_context)
            except Exception as e:
                raise PluginLoadingError(f"Plugin {plugin} failed to initialize: {e!r}") from e
        else:
            _legacy_extension_init(
                plugin_name=plugin,
                key=req.key,
                entries=entries,
                build_configuration=build_configuration,
                loaded=loaded,
            )

        loaded[dist.as_requirement().key] = dist


def load_build_configuration_from_source(
    build_configuration: BuildConfiguration.Builder, backends: list[str]
) -> None:
    """Installs pants backend packages to provide BUILD file symbols and cli goals.

    :param build_configuration: The BuildConfiguration (for adding aliases).
    :param backends: An list of packages to load v2 backends from.
    :raises: :class:``pants.base.exceptions.BuildConfigurationError`` if there is a problem loading
      the build configuration.
    """
    # NB: Backends added here must be explicit dependencies of this module.
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

    def invoke_entrypoint(name: str):
        entrypoint = getattr(module, name, lambda: None)
        try:
            return entrypoint()
        except TypeError as e:
            traceback.print_exc()
            raise BackendConfigurationError(
                f"Entrypoint {name} in {backend_module} must be a zero-arg callable: {e!r}"
            )

    if hasattr(module, _EXTENSION_INITIALIZE_METHOD_NAME):
        initializer = getattr(module, _EXTENSION_INITIALIZE_METHOD_NAME)
        initializer_context = PluginExtensionInitContext(
            key=backend_package, build_configuration=build_configuration
        )
        try:
            initializer(initializer_context)
        except Exception as e:
            raise BackendConfigurationError(
                f"Backend {backend_package} failed to initialize: {e!r}"
            ) from e
    else:
        target_types = invoke_entrypoint("target_types")
        if target_types:
            build_configuration.register_target_types(backend_package, target_types)
        build_file_aliases = invoke_entrypoint("build_file_aliases")
        if build_file_aliases:
            build_configuration.register_aliases(build_file_aliases)
        rules = invoke_entrypoint("rules")
        if rules:
            build_configuration.register_rules(backend_package, rules)
        remote_auth_func = getattr(module, "remote_auth", None)
        if remote_auth_func:
            logger.debug(
                f"register remote auth function {remote_auth_func.__module__}.{remote_auth_func.__name__} from backend: {backend_package}"
            )
            build_configuration.register_remote_auth_plugin(remote_auth_func)
        auxiliary_goals = invoke_entrypoint("auxiliary_goals")
        if auxiliary_goals:
            build_configuration.register_auxiliary_goals(backend_package, auxiliary_goals)
