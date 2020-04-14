# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate web service client stubs from a Web Services Description Language (WSDL) file for
calling a JAX-WS web service (deprecated)."""

from pants.base.deprecated import _deprecated_contrib_plugin
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.jax_ws.rules.targets import JaxWsLibrary
from pants.contrib.jax_ws.targets.jax_ws_library import JaxWsLibrary as JaxWsLibraryV1
from pants.contrib.jax_ws.tasks.jax_ws_gen import JaxWsGen

_deprecated_contrib_plugin("pantsbuild.pants.contrib.jax_ws")


def build_file_aliases():
    return BuildFileAliases(targets={"jax_ws_library": JaxWsLibraryV1})


def register_goals():
    task(name="jax-ws", action=JaxWsGen).install("gen")


def targets2():
    return [JaxWsLibrary]
