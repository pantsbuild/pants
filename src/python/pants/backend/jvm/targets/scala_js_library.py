# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.scala_js_platform import ScalaJSPlatform
from pants.backend.jvm.targets.scala_library import ScalaLibrary


class ScalaJSLibrary(ScalaLibrary):
  """Extends ScalaLibrary to inject scala-js deps and request ScalaJS compilation."""

  @classmethod
  def subsystems(cls):
    return super(ScalaJSLibrary, cls).subsystems() + (ScalaJSPlatform, )

  @property
  def traversable_dependency_specs(self):
    for spec in super(ScalaJSLibrary, self).traversable_dependency_specs:
      yield spec
    for library_spec in ScalaJSPlatform.global_instance().runtime:
      yield library_spec
