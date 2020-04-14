# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, Target

from pants.contrib.node.rules.targets import NodeModule


class ScalaJSBinary(Target):
    """A binary JavaScript blob built from a collection of `scala_js_library` targets.

    This can be consumed by NPM and Node.
    """

    alias = "scala_js_binary"
    core_fields = NodeModule.core_fields
    v1_only = True


class ScalaJSLibrary(Target):
    """A library with Scala sources which are intended to be compiled to JavaScript.

    Linking multiple libraries together into a shippable blob additionally requires a
    `scala_js_binary` target.
    """

    alias = "scala_js_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, Sources)
    v1_only = True
