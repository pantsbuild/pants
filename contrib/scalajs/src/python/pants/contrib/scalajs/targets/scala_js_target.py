# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

from pants.contrib.scalajs.subsystems.scala_js_platform import ScalaJSPlatform


class ScalaJSTarget(object):
  """A mixin for ScalaJS targets to injects scala-js deps and request ScalaJS compilation."""

  @classmethod
  def subsystems(cls):
    return super(ScalaJSTarget, cls).subsystems() + (JvmPlatform, ScalaJSPlatform)

  def __init__(self, address=None, payload=None, **kwargs):
    self.address = address  # Set in case a TargetDefinitionException is thrown early
    payload = payload or Payload()
    payload.add_fields({
      'platform': PrimitiveField(None),
    })
    super(ScalaJSTarget, self).__init__(address=address, payload=payload, **kwargs)

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(ScalaJSTarget, cls).compute_dependency_specs(kwargs, payload):
      yield spec
    for spec in ScalaJSPlatform.global_instance().injectables_specs_for_key('runtime'):
      yield spec

  @property
  def strict_deps(self):
    return False

  @property
  def fatal_warnings(self):
    return False

  @property
  def zinc_file_manager(self):
    return False

  @property
  def platform(self):
    return JvmPlatform.global_instance().get_platform_for_target(self)
