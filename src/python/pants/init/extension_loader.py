# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import importlib.metadata
import logging
import traceback
from importlib.metadata import Distribution

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import NormalizedName, canonicalize_name

from pants.base.exceptions import BackendConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.goal.builtins import register_builtin_goals
from pants.init.import_util import find_matching_distributions
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


class PluginLoadingError(Exception):
    pass


class PluginNotFound(PluginLoadingError):
    pass


class PluginLoadOrderError(PluginLoadingError):
    pass


def load_backends_and_plugins(
    plugins: list[str],
    backends: list[str],
    bc_builder: BuildConfiguration.Builder,
) -> BuildConfiguration:
    """Load named plugins and source backends.

    :param plugins: plugins to load.
    :param backends: backends to load.
    :param bc_builder: The BuildConfiguration (for adding aliases).
    """
    load_build_configuration_from_source(bc_builder, backends)
    load_plugins(bc_builder, plugins)
    if not bc_builder._pants_ng:
        register_builtin_goals(bc_builder)
    return bc_builder.create()


def load_plugins(
    build_configuration: BuildConfiguration.Builder,
    plugins: list[str],
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
    """

    loaded: dict[NormalizedName, Distribution] = {}
    for plugin in plugins or []:
        try:
            req = Requirement(plugin)
            req_key = canonicalize_name(req.name)
        except InvalidRequirement:
            raise PluginNotFound(f"Could not find plugin: {req}")

        dists = list(find_matching_distributions(req))
        if not dists:
            raise PluginNotFound(f"Could not find plugin: {req}")
        dist = dists[0]

        entry_points = dist.entry_points.select(group="pantsbuild.plugin")

        def find_entry_point(entry_point_name: str) -> importlib.metadata.EntryPoint | None:
            for entry_point in entry_points:
                if entry_point.name == entry_point_name:
                    return entry_point
            return None

        if load_after_entry_point := find_entry_point("load_after"):
            deps = load_after_entry_point.load()()
            for dep_name in deps:
                dep = Requirement(dep_name)
                dep_key = canonicalize_name(dep.name)
                if dep_key not in loaded:
                    raise PluginLoadOrderError(f"Plugin {plugin} must be loaded after {dep}")
        if target_types_entry_point := find_entry_point("target_types"):
            target_types = target_types_entry_point.load()()
            build_configuration.register_target_types(req_key, target_types)
        if build_file_aliases_entry_point := find_entry_point("build_file_aliases"):
            aliases = build_file_aliases_entry_point.load()()
            build_configuration.register_aliases(aliases)
        if rules_entry_point := find_entry_point("rules"):
            rules = rules_entry_point.load()()
            build_configuration.register_rules(req_key, rules)
        if remote_auth_entry_point := find_entry_point("remote_auth"):
            remote_auth_func = remote_auth_entry_point.load()
            logger.debug(
                f"register remote auth function {remote_auth_func.__module__}.{remote_auth_func.__name__} from plugin: {plugin}"
            )
            build_configuration.register_remote_auth_plugin(remote_auth_func)
        if auxiliary_goals_entry_point := find_entry_point("auxiliary_goals"):
            auxiliary_goals = auxiliary_goals_entry_point.load()()
            build_configuration.register_auxiliary_goals(req_key, auxiliary_goals)

        loaded[req_key] = dist


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
