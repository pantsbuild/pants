# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from builtins import open

from pants.backend.codegen.protobuf.subsystems.protoc import Protoc
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.option.custom_types import target_option
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess
from twitter.common.collections import OrderedSet

from pants.contrib.go.subsystems.protoc_gen_go import ProtocGenGo
from pants.contrib.go.targets.go_protobuf_library import GoProtobufGenLibrary, GoProtobufLibrary


class GoProtobufGen(SimpleCodegenTask):

  sources_globs = ('**/*',)

  _NAMESPACE_PARSER = re.compile(r'^\s*option\s+go_package\s*=\s*"([^\s]+)"\s*;', re.MULTILINE)
  _PACKAGE_PARSER = re.compile(r'^\s*package\s+([^\s]+)\s*;', re.MULTILINE)

  @classmethod
  def register_options(cls, register):
    super(GoProtobufGen, cls).register_options(register)

    register('--import-target', type=target_option, fingerprint=True,
             help='Target that will be added as a dependency of protoc-generated Go code.')
    register('--protoc-plugins', type=list, fingerprint=True,
             help='List of protoc plugins to activate.  E.g., grpc.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(GoProtobufGen, cls).subsystem_dependencies() + (Protoc.scoped(cls), ProtocGenGo,)

  @memoized_property
  def _protoc(self):
    return Protoc.scoped_instance(self).select(context=self.context)

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    import_target = self.get_options().import_target
    if import_target is None:
      raise TaskError('Option import_target in scope {} must be set.'.format(
        self.options_scope))
    return self.context.resolve(import_target)

  def synthetic_target_type(self, target):
    return GoProtobufGenLibrary

  def is_gentarget(self, target):
    return isinstance(target, GoProtobufLibrary)

  @classmethod
  def product_types(cls):
    return ['go']

  def execute_codegen(self, target, target_workdir):
    target_cmd = [self._protoc]

    protoc_gen_go = ProtocGenGo.global_instance().select(self.context)
    env = os.environ.copy()
    env['PATH'] = ':'.join([os.path.dirname(protoc_gen_go), env['PATH']])

    bases = OrderedSet(tgt.target_base for tgt in target.closure() if self.is_gentarget(tgt))
    for base in bases:
      target_cmd.append('-I={}'.format(os.path.join(get_buildroot(), base)))

    outdir = os.path.join(target_workdir, 'src', 'go')
    safe_mkdir(outdir)
    protoc_plugins = self.get_options().protoc_plugins + list(target.protoc_plugins)
    if protoc_plugins:
      go_out = 'plugins={}:{}'.format('+'.join(protoc_plugins), outdir)
    else:
      go_out = outdir
    target_cmd.append('--go_out={}'.format(go_out))

    all_sources = list(target.sources_relative_to_buildroot())
    for source in all_sources:
      file_cmd = target_cmd + [os.path.join(get_buildroot(), source)]
      with self.context.new_workunit(name=source,
                                     labels=[WorkUnitLabel.TOOL],
                                     cmd=' '.join(file_cmd)) as workunit:
        self.context.log.info(' '.join(file_cmd))
        result = subprocess.call(file_cmd,
                                 env=env,
                                 stdout=workunit.output('stdout'),
                                 stderr=workunit.output('stderr'))
        if result != 0:
          raise TaskError('{} ... exited non-zero ({})'.format(self._protoc, result))

  @property
  def _copy_target_attributes(self):
    return [a for a in super(GoProtobufGen, self)._copy_target_attributes if a != 'provides']

  def synthetic_target_dir(self, target, target_workdir):
    all_sources = list(target.sources_relative_to_buildroot())
    source = all_sources[0]
    namespace = self._get_go_namespace(source)
    return os.path.join(target_workdir, 'src', 'go', namespace)

  @classmethod
  def _get_go_namespace(cls, source):
    with open(source, 'r') as fh:
      data = fh.read()
    namespace = cls._NAMESPACE_PARSER.search(data)
    if not namespace:
      namespace = cls._PACKAGE_PARSER.search(data)
    return namespace.group(1)
