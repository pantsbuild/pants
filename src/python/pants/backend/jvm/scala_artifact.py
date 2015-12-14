# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform


class ScalaArtifact(Artifact):
  """Extends Artifact to append the configured Scala version."""

  @property
  def name(self):
    return ScalaPlatform.global_instance().suffix_version(self._base_name)
