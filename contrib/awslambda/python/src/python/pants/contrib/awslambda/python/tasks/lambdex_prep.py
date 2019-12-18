# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.tasks.python_tool_prep_base import PythonToolInstance, PythonToolPrepBase

from pants.contrib.awslambda.python.subsystems.lambdex import Lambdex


class LambdexInstance(PythonToolInstance):
  pass


class LambdexPrep(PythonToolPrepBase):
  tool_subsystem_cls = Lambdex
  tool_instance_cls = LambdexInstance
