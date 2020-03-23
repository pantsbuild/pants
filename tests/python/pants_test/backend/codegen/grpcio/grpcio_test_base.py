# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.codegen.grpcio.python.grpcio_prep import GrpcioPrep
from pants.backend.codegen.grpcio.python.grpcio_run import GrpcioRun
from pants.backend.python.targets.python_library import PythonLibrary
from pants.testutil.task_test_base import TaskTestBase


class GrpcioTestBase(TaskTestBase):
    @classmethod
    def task_type(cls):
        return GrpcioRun

    def generate_grpcio_targets(self, python_grpcio_library):
        grpcio_prep_task_type = self.synthesize_task_subtype(GrpcioPrep, "gp")
        context = self.context(
            for_task_types=[grpcio_prep_task_type], target_roots=[python_grpcio_library]
        )

        grpcio_prep = grpcio_prep_task_type(context, os.path.join(self.pants_workdir, "gp"))
        grpcio_prep.execute()

        grpcio_gen = self.create_task(context)
        grpcio_gen.execute()

        def is_synthetic_python_library(target):
            return isinstance(target, PythonLibrary) and target.is_synthetic

        return context.targets(predicate=is_synthetic_python_library)
