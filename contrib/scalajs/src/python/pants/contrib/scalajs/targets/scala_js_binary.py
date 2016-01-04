# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.scalajs.targets.scala_js_target import ScalaJSTarget


class ScalaJSBinary(ScalaJSTarget, NodeModule):
  """A binary javascript blob built from a collection of ScalaJSLibrary targets.

  Extends NodeModule to allow consumption by NPM and node.
  """
  pass
