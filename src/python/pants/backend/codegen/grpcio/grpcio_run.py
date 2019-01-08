# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import logging
from collections import OrderedDict

from pants.backend.codegen.grpcio.grpcio_prep import GrpcioPrep
from pants.backend.codegen.grpcio.python_grpcio_library import PythonGrpcioLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.contextutil import pushd
from pants.util.memo import memoized_property


class GrpcioRun(SimpleCodegenTask):
  """Task to compile protobuf"""

  gentarget_type = PythonGrpcioLibrary
  sources_globs = ('**/*',)

  @classmethod
  def prepare(cls, options, round_manager):
    super(GrpcioRun, cls).prepare(options, round_manager)
    round_manager.require_data(GrpcioPrep.tool_instance_cls)

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
      logging.debug("Grpcio finished code generation")

  def build_args(self, target, target_workdir):
    python_out = '--python_out={0}'.format(target_workdir)
    grpc_python_out = '--grpc_python_out={0}'.format(target_workdir)

    args = [python_out, grpc_python_out]

    sources = []
    sources_by_base = self._calculate_sources(target)
    for (base, source_list) in sources_by_base.items():
      args.append('--proto_path={0}'.format(base))
      sources.extend(source_list)

    # We need those sources to be added as a very last in args array
    args.extend(sources)
    return args

  def _calculate_sources(self, target):
    gentargets = set()

    def add_to_gentargets(tgt):
      if self.is_gentarget(tgt):
        gentargets.add(tgt)

    self.context.build_graph.walk_transitive_dependency_graph(
      [target.address],
      add_to_gentargets,
      postorder=True)
    sources_by_base = OrderedDict()
    for gentarget in gentargets:
      base = gentarget.target_base
      if base not in sources_by_base:
        sources_by_base[base] = set()
      sources_by_base[base].update(gentarget.sources_relative_to_buildroot())
    return sources_by_base

  def synthetic_target_type(self, target):
    return PythonLibrary
