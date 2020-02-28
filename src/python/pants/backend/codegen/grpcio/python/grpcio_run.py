# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import logging
from pathlib import Path

from pants.backend.codegen.grpcio.python.grpcio_prep import GrpcioPrep
from pants.backend.codegen.grpcio.python.python_grpcio_library import PythonGrpcioLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.python.pex_build_util import identify_missing_init_files
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.contextutil import pushd
from pants.util.memo import memoized_property


class GrpcioRun(SimpleCodegenTask):
    """Task to compile protobuf into python code."""

    gentarget_type = PythonGrpcioLibrary
    sources_globs = ("**/*",)

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(GrpcioPrep.tool_instance_cls)

    def synthetic_target_type(self, target):
        return PythonLibrary

    @memoized_property
    def _grpcio_binary(self):
        return self.context.products.get_data(GrpcioPrep.tool_instance_cls)

    def execute_codegen(self, target, target_workdir):
        args = self.build_args(target, target_workdir)
        logging.debug(f"Executing grpcio code generation with args: [{args}]")

        with pushd(get_buildroot()):
            workunit_factory = functools.partial(
                self.context.new_workunit,
                name="run-grpcio",
                labels=[WorkUnitLabel.TOOL, WorkUnitLabel.LINT],
            )
            cmdline, exit_code = self._grpcio_binary.run(workunit_factory, args)
            if exit_code != 0:
                raise TaskError(
                    f"{cmdline} ... exited non-zero ({exit_code}).", exit_code=exit_code
                )
            # Create __init__.py in each subdirectory of the target directory so that setup_py recognizes
            # them as modules.
            target_workdir_path = Path(target_workdir)
            sources = [
                str(p.relative_to(target_workdir_path)) for p in target_workdir_path.rglob("*.py")
            ]
            for missing_init in identify_missing_init_files(sources):
                Path(target_workdir_path, missing_init).touch()
            logging.info(f"Grpcio finished code generation into: [{target_workdir}]")

    def build_args(self, target, target_workdir):
        proto_path = f"--proto_path={target.target_base}"
        python_out = f"--python_out={target_workdir}"
        grpc_python_out = f"--grpc_python_out={target_workdir}"

        args = [python_out, grpc_python_out, proto_path]

        args.extend(target.sources_relative_to_buildroot())
        return args
