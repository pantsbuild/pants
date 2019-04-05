# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.subsystems.conan import Conan
from pants.backend.native.targets.external_native_library import ExternalNativeLibrary
from pants.backend.python.tasks.python_tool_prep_base import PythonToolInstance, PythonToolPrepBase


class ConanInstance(PythonToolInstance):
  pass


class ConanPrep(PythonToolPrepBase):
  tool_subsystem_cls = Conan
  tool_instance_cls = ConanInstance

  def will_be_invoked(self):
    return any(self.get_targets(lambda t: isinstance(t, ExternalNativeLibrary)))
