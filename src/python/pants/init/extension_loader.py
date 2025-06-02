# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import importlib.metadata
import importlib.util
import logging
import re
import traceback

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from pants.base.exceptions import BackendConfigurationError
from pants.build_graph.build_configuration import BuildConfiguration
from pants.goal.builtins import register_builtin_goals
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
    bc_builder: BuildConfiguration.Builder | None = None,
) -> BuildConfiguration:
    """Load named plugins and source backends.

    :param plugins: v2 plugins to load.
    :param backends: v2 backends to load.
    :param bc_builder: The BuildConfiguration (for adding aliases).
    """
    bc_builder = bc_builder or BuildConfiguration.Builder()
    load_build_configuration_from_source(bc_builder, backends)
    load_plugins(bc_builder, plugins)
    register_builtin_goals(bc_builder)
    return bc_builder.create()


def _normalize_name(name: str) -> str:
    """Normalize package names according to PEP 508.

    Convert to lowercase and replace underscores/dots with hyphens.
    """
    return name.lower().replace("_", "-").replace(".", "-")


def _distribution_matches_requirement(
    dist: importlib.metadata.Distribution, requirement: Requirement
) -> bool:
    """Check if a distribution matches a requirement.

    Args:
        dist: Distribution to check
        requirement: Requirement to match against

    Returns:
        True if the distribution matches the requirement
    """
    # Check name match (case-insensitive, normalize underscores/hyphens)
    dist_name = _normalize_name(dist.metadata["Name"])
    req_name = _normalize_name(requirement.name)

    if dist_name != req_name:
        return False

    # If no version specifier, name match is sufficient
    if not requirement.specifier:
        return True

    # Check version specifier
    try:
        dist_version = Version(dist.version)
        return requirement.specifier.contains(dist_version)
    except InvalidVersion:
        # If we can't parse the version, assume it doesn't match
        return False


def _find_all_matching_distributions(
    requirement: Requirement,
) -> list[importlib.metadata.Distribution]:
    """Internal function to find all matching distributions."""
    matching_dists = []

    for dist in importlib.metadata.distributions():
        if _distribution_matches_requirement(dist, requirement):
            matching_dists.append(dist)

    return matching_dists


def find_all_distributions_by_requirement(
    requirement: Requirement, search_paths: list[str] | None = None
) -> list[importlib.metadata.Distribution]:
    """Find all distributions that match the given requirement.

    Args:
        requirement: A packaging.requirements.Requirement object
        search_paths: Optional list of paths to search in addition to sys.path

    Returns:
        List of all matching Distribution objects
    """
    matching_dists: list[importlib.metadata.Distribution] = []

    # Search in current environment (avoid duplicates)
    current_matches = _find_all_matching_distributions(requirement)
    seen_names = {dist.metadata["Name"] for dist in matching_dists}

    for dist in current_matches:
        if dist.metadata["Name"] not in seen_names:
            matching_dists.append(dist)

    return matching_dists


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

    def _requirement_key(req: Requirement) -> str:
        return re.sub("[^A-Za-z0-9.]+", "-", req.name).lower()

    loaded: dict = {}
    for plugin in plugins or []:
        try:
            req = Requirement(plugin)
            req_key = _requirement_key(req)
        except InvalidRequirement:
            raise PluginNotFound(f"Could not find plugin: {req}")

        dists = [d for d in _find_all_matching_distributions(req) if d]
        if len(dists) > 1:
            msg = ", ".join(repr(d) for d in dists)
            raise PluginNotFound(f"Multiple Python distributions match plugin `{req}`: {msg}")
        dist = dists[0]

        entry_points = dist.entry_points.select(group="pantsbuild.plugin")

        if "load_after" in entry_points:
            deps = entry_points["load_after"].load()()
            for dep_name in deps:
                dep = Requirement(dep_name)
                dep_key = _requirement_key(dep)
                if dep_key not in loaded:
                    raise PluginLoadOrderError(f"Plugin {plugin} must be loaded after {dep}")
        if "target_types" in entry_points:
            target_types = entry_points["target_types"].load()()
            build_configuration.register_target_types(req_key, target_types)
        if "build_file_aliases" in entry_points:
            aliases = entry_points["build_file_aliases"].load()()
            build_configuration.register_aliases(aliases)
        if "rules" in entry_points:
            rules = entry_points["rules"].load()()
            build_configuration.register_rules(req_key, rules)
        if "remote_auth" in entry_points:
            remote_auth_func = entry_points["remote_auth"].load()
            logger.debug(
                f"register remote auth function {remote_auth_func.__module__}.{remote_auth_func.__name__} from plugin: {plugin}"
            )
            build_configuration.register_remote_auth_plugin(remote_auth_func)
        if "auxiliary_goals" in entry_points:
            auxiliary_goals = entry_points["auxiliary_goals"].load()()
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
