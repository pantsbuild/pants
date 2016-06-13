# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.java.distribution.distribution import DistributionLocator


class ToolsJar(JvmTarget):
  """A private target type injected by the ProvideToolsJar task to represent the JDK's tools.jar."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(JavacPlugin, cls).subsystem_dependencies() + (DistributionLocator,)
