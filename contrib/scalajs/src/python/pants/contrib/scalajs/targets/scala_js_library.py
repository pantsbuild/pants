# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.target import Target

from pants.contrib.scalajs.targets.scala_js_target import ScalaJSTarget


class ScalaJSLibrary(ScalaJSTarget, Target):
  """A library with scala sources, intended to be compiled to Javascript.

  Linking multiple libraries together into a shippable blob additionally requires a
  ScalaJSBinary target.
  """
