# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for Scala.js (deprecated)."""

from pants.base.deprecated import _deprecated_contrib_plugin
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.node.tasks.node_resolve import NodeResolve
from pants.contrib.scalajs.rules.targets import ScalaJSBinary, ScalaJSLibrary
from pants.contrib.scalajs.subsystems.scala_js_platform import ScalaJSPlatform
from pants.contrib.scalajs.targets.scala_js_binary import ScalaJSBinary as ScalaJSBinaryV1
from pants.contrib.scalajs.targets.scala_js_library import ScalaJSLibrary as ScalaJSLibraryV1
from pants.contrib.scalajs.tasks.scala_js_link import ScalaJSLink
from pants.contrib.scalajs.tasks.scala_js_zinc_compile import ScalaJSZincCompile

_deprecated_contrib_plugin("pantsbuild.pants.contrib.scalajs")


def build_file_aliases():
    return BuildFileAliases(
        targets={"scala_js_binary": ScalaJSBinaryV1, "scala_js_library": ScalaJSLibraryV1}
    )


def register_goals():
    NodeResolve.register_resolver_for_type(ScalaJSBinaryV1, ScalaJSPlatform)
    # NB: These task/goal assignments are pretty nuts, but are necessary in order to
    # prevent product-graph cycles between the JVM and node.js.
    #   see https://github.com/pantsbuild/pants/labels/engine
    task(name="scala-js-compile", action=ScalaJSZincCompile).install("resolve")
    task(name="scala-js-link", action=ScalaJSLink).install("resolve")


def global_subsystems():
    return {ScalaJSPlatform}


def targets2():
    return [ScalaJSBinary, ScalaJSLibrary]
