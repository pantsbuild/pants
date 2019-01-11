# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.codegen.grpcio.grpcio import Grpcio
from pants.backend.python.tasks.python_tool_prep_base import PythonToolInstance, PythonToolPrepBase


class GrpcioInstance(PythonToolInstance):
  pass


class GrpcioPrep(PythonToolPrepBase):
  tool_subsystem_cls = Grpcio
  tool_instance_cls = GrpcioInstance
