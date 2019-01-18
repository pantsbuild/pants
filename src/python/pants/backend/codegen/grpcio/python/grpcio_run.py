# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import logging

from pants.backend.codegen.grpcio.python.grpcio_prep import GrpcioPrep
from pants.backend.codegen.grpcio.python.python_grpcio_library import PythonGrpcioLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.contextutil import pushd
from pants.util.memo import memoized_property


class GrpcioRun(SimpleCodegenTask):
  """Task to compile protobuf into python code"""

  gentarget_type = PythonGrpcioLibrary
  sources_globs = ('**/*',)

  @classmethod
  def prepare(cls, options, round_manager):
    super(GrpcioRun, cls).prepare(options, round_manager)
    round_manager.require_data(GrpcioPrep.tool_instance_cls)

  def synthetic_target_type(self, target):
    return PythonLibrary

  @memoized_property
  def _grpcio_binary(self):
    return self.context.products.get_data(GrpcioPrep.tool_instance_cls)

  def execute_codegen(self, target, target_workdir):
    args = self.build_args(target, target_workdir)
    logging.debug("Executing grpcio code generation with args: [{}]".format(args))

    with pushd(get_buildroot()):
      workunit_factory = functools.partial(self.context.new_workunit,
                                           name='run-grpcio',
                                           labels=[WorkUnitLabel.TOOL, WorkUnitLabel.LINT])
      cmdline, exit_code = self._grpcio_binary.run(workunit_factory, args)
      if exit_code != 0:
        raise TaskError('{} ... exited non-zero ({}).'.format(cmdline, exit_code),
                        exit_code=exit_code)
      logging.info("Grpcio finished code generation into: [{}]".format(target_workdir))

  def build_args(self, target, target_workdir):
    proto_path = '--proto_path={0}'.format(target.target_base)
    python_out = '--python_out={0}'.format(target_workdir)
    grpc_python_out = '--grpc_python_out={0}'.format(target_workdir)

    args = [python_out, grpc_python_out, proto_path]

    args.extend(target.sources_relative_to_buildroot())
    return args
