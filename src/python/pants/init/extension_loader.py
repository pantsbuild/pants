# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import traceback
from textwrap import fill, indent
from typing import Dict, List

from pkg_resources import Requirement, WorkingSet

from pants.base.deprecated import warn_or_error
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
    build_configuration: BuildConfiguration,
) -> BuildConfiguration:
    """Load named plugins and source backends.

    :param plugins1: v1 plugins to load.
    :param plugins2: v2 plugins to load.
    :param working_set: A pkg_resources.WorkingSet to load plugins from.
    :param backends1: v1 backends to load.
    :param backends2: v2 backends to load.
    :param build_configuration: The BuildConfiguration (for adding aliases).
    """
    used_deprecated_backends = set(backends1).intersection(
        {
            "pants.backend.codegen.antlr.java",
            "pants.backend.codegen.antlr.python",
            "pants.backend.codegen.jaxb",
            "pants.backend.codegen.ragel.java",
            "pants.backend.codegen.wire.java",
        }
    )
    if used_deprecated_backends:
        formatted_backends = "\n  * ".join(sorted(used_deprecated_backends))
        toml_backends = ",\n  ".join(repr(backend) for backend in sorted(used_deprecated_backends))
        toml_config = indent(f"[GLOBAL]\nbackend_packages.remove = [\n  {toml_backends},\n]", "  ",)
        ini_backends = ",\n    ".join(repr(backend) for backend in sorted(used_deprecated_backends))
        ini_config = indent(f"[GLOBAL]\nbackend_packages = -[\n    {ini_backends},\n  ]", "  ")
        msg = (
            "\nYou have activated the following backend packages, which are planned to be removed "
            f"due to low usage:\n\n  * {formatted_backends}\n\nTo prepare for this "
            f"change, add this to your `pants.toml`:\n\n{toml_config}\n\nOr add this to your "
            f"`pants.ini`:\n\n{ini_config}\n\nIf you still depend on any of these backends, please "
            "email pants-devel <pants-devel@googlegroups.com> or message us on Slack and we will "
            "keep the backend."
        )
        warn_or_error(
            deprecated_entity_description="the antlr, jaxb, ragel, and wire codegen backends",
            removal_version="1.29.0.dev0",
            hint="\n".join(fill(line, 80) for line in msg.splitlines()),
            stacklevel=4,
        )
    if "pants.backend.python.lint.isort" in backends1:
        reasons = [
            indent(fill(reason, 78), "  ")
            for reason in [
                "1) Avoids unnecessary prework. This new implementation should be faster to run.",
                (
                    "2) Has less verbose output. Pants will now only show what isort itself outputs. "
                    "(Use `--v2-ui` if you want to see the work Pants is doing behind-the-scenes.)"
                ),
                (
                    "3) Works with `./pants lint` automatically. When you run `./pants lint`, Pants "
                    "will run isort in check-only mode."
                ),
                (
                    "4) Works with precise file arguments. If you say `./pants fmt f1.py`, Pants "
                    "will only run over the file `f1.py`, whereas the old implementation would run "
                    "over every file belonging to the target that owns `f1.py`."
                ),
            ]
        ]
        msg_lines = [
            fill(
                (
                    "The original isort implementation is being replaced by an improved "
                    "implementation made possible by the V2 engine. This new implementation "
                    "brings these benefits:"
                ),
                80,
            ),
            "",
            *(f"{reason}\n" for reason in reasons),
            "",
            fill(
                (
                    "To prepare for this change, add to the `GLOBAL` section in your `pants.toml` "
                    "the line `backend_packages.remove = ['pants.backend.python.lint.isort']` "
                    "(or `backend_packages = -['pants.backend.python.lint.isort']` to your "
                    "`pants.ini`)."
                ),
                80,
            ),
            "",
            fill(
                (
                    "If you still want to use isort, add `backend_packages2.add = "
                    "['pants.backend.python.lint.isort']` to `pants.toml` or `backend_packages2 = "
                    "+['pants.backend.python.lint.isort']` to your `pants.ini`. Ensure that you "
                    "have `--v2` enabled (the default value)."
                ),
                80,
            ),
        ]
        warn_or_error(
            deprecated_entity_description="The V1 isort implementation",
            removal_version="1.30.0.dev0",
            deprecation_start_version="1.28.0.dev0",
            hint="\n".join(msg_lines),
        )

    if "pants.contrib.awslambda.python" in backends1:
        msg_lines = [
            fill(
                (
                    "The original awslambda implementation is being replaced by an improved "
                    "implementation made possible by the V2 engine."
                ),
                80,
            ),
            "",
            fill(
                (
                    "To prepare for this change, remove 'pants.contrib.awslambda.python' from the "
                    "`backend_packages` entry in the `GLOBAL` section in your `pants.toml` "
                    "(or `pants.ini`). Then add `pants.backend.awslambda.python` to the "
                    "`backend_packages2` entry. Ensure that you have `--v2` enabled (the default). "
                    "Then modify your BUILD files to remove the intermediate `python_binary` "
                    "target and the `binary=` setting on the `python_awslambda` target. "
                    "Finally, use the `awslambda` goal instead of the `bundle` goal."
                ),
                80,
            ),
        ]
        warn_or_error(
            deprecated_entity_description="The V1 awslambda implementation",
            removal_version="1.30.0.dev0",
            deprecation_start_version="1.28.0.dev0",
            hint="\n".join(msg_lines),
        )

    load_build_configuration_from_source(build_configuration, backends1, backends2)
    load_plugins(build_configuration, plugins1, working_set, is_v1_plugin=True)
    load_plugins(build_configuration, plugins2, working_set, is_v1_plugin=False)
    return build_configuration


def load_plugins(
    build_configuration: BuildConfiguration,
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
        if "targets2" in entries:
            targets = entries["targets2"].load()()
            build_configuration.register_targets(targets)

        if is_v1_plugin:
            if "register_goals" in entries:
                entries["register_goals"].load()()
            if "global_subsystems" in entries:
                subsystems = entries["global_subsystems"].load()()
                build_configuration.register_optionables(subsystems)
            # For now, `build_file_aliases` is still V1-only. TBD what entry-point we use for
            # `objects` and `context_aware_object_factories`.
            if "build_file_aliases" in entries:
                aliases = entries["build_file_aliases"].load()()
                build_configuration.register_aliases(aliases)
        else:
            if "rules" in entries:
                rules = entries["rules"].load()()
                build_configuration.register_rules(rules)
            if "build_file_aliases2" in entries:
                build_file_aliases2 = entries["build_file_aliases2"].load()()
                build_configuration.register_aliases(build_file_aliases2)
        loaded[dist.as_requirement().key] = dist


def load_build_configuration_from_source(
    build_configuration: BuildConfiguration, backends1: List[str], backends2: List[str]
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

    backend_packages2 = FrozenOrderedSet(["pants.rules.core", *backends2])
    for backend_package in backend_packages2:
        load_backend(build_configuration, backend_package, is_v1_backend=False)


def load_backend(
    build_configuration: BuildConfiguration, backend_package: str, is_v1_backend: bool
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

    # While the Target API is a V2 concept, we expect V1 plugin authors to still write Target
    # API bindings. So, we end up using this entry point regardless of V1 vs. V2.
    targets = invoke_entrypoint("targets2")
    if targets:
        build_configuration.register_targets(targets)

    if is_v1_backend:
        invoke_entrypoint("register_goals")
        subsystems = invoke_entrypoint("global_subsystems")
        if subsystems:
            build_configuration.register_optionables(subsystems)
        # For now, `build_file_aliases` is still V1-only. TBD what entry-point we use for
        # `objects` and `context_aware_object_factories`.
        build_file_aliases = invoke_entrypoint("build_file_aliases")
        if build_file_aliases:
            build_configuration.register_aliases(build_file_aliases)
    else:
        rules = invoke_entrypoint("rules")
        if rules:
            build_configuration.register_rules(rules)
        build_file_aliases2 = invoke_entrypoint("build_file_aliases2")
        if build_file_aliases2:
            build_configuration.register_aliases(build_file_aliases2)
