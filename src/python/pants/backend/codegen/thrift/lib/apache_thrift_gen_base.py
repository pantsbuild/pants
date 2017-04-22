# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import shutil
import subprocess

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.binaries.thrift_binary import ThriftBinary
from pants.option.custom_types import target_option
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.memo import memoized_property


class ApacheThriftGenBase(SimpleCodegenTask):
  # The name of the thrift generator to use. Subclasses must set.
  # E.g., java, py (see `thrift -help` for all available generators).
  thrift_generator = None

  # Subclasses may set their own default generator options.
  default_gen_options_map = None

  @classmethod
  def register_options(cls, register):
    super(ApacheThriftGenBase, cls).register_options(register)

    # NB: As of thrift 0.9.2 there is 1 warning that -strict promotes to an error - missing a
    # struct field id.  If an artifact was cached with strict off, we must re-gen with strict on
    # since this case may be present and need to generate a thrift compile error.
    register('--strict', default=True, fingerprint=True, type=bool,
             help='Run thrift compiler with strict warnings.')
    # The old --gen-options was string-typed, so we keep it that way for backwards compatibility,
    # and reluctantly use the clunky name --gen-options-map for the new, map-typed options.
    # TODO: Once --gen-options is gone, do a deprecation cycle to restore the old name.
    register('--gen-options', advanced=True, fingerprint=True,
             removal_version='1.5.0.dev0', removal_hint='Use --gen-options-map instead',
             help='Use these options for the {} generator.'.format(cls.thrift_generator))
    register('--gen-options-map', type=dict, advanced=True, fingerprint=True,
             default=cls.default_gen_options_map,
             help='Use these options for the {} generator.'.format(cls.thrift_generator))
    register('--deps', advanced=True, type=list, member_type=target_option,
             help='A list of specs pointing to dependencies of thrift generated code.')
    register('--service-deps', advanced=True, type=list, member_type=target_option,
             help='A list of specs pointing to dependencies of thrift generated service '
                  'code.  If not supplied, then --deps will be used for service deps.')

  @classmethod
  def subsystem_dependencies(cls):
    return (super(ApacheThriftGenBase, cls).subsystem_dependencies() +
            (ThriftBinary.Factory.scoped(cls),))

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    for source in target.sources_relative_to_buildroot():
      if self._declares_service(os.path.join(get_buildroot(), source)):
        return self._service_deps
    return self._deps

  def execute_codegen(self, target, target_workdir):
    target_cmd = self._thrift_cmd[:]

    bases = OrderedSet(tgt.target_base for tgt in target.closure() if self.is_gentarget(tgt))
    for base in bases:
      target_cmd.extend(('-I', base))

    target_cmd.extend(('-o', target_workdir))

    for source in target.sources_relative_to_buildroot():
      cmd = target_cmd[:]
      cmd.append(os.path.join(get_buildroot(), source))
      with self.context.new_workunit(name=source,
                                     labels=[WorkUnitLabel.TOOL],
                                     cmd=' '.join(cmd)) as workunit:
        result = subprocess.call(cmd,
                                 stdout=workunit.output('stdout'),
                                 stderr=workunit.output('stderr'))
        if result != 0:
          raise TaskError('{} ... exited non-zero ({})'.format(self._thrift_binary, result))

    # The thrift compiler generates sources to a gen-[lang] subdir of the `-o` argument.  We
    # relocate the generated sources to the root of the `target_workdir` so that our base class
    # maps them properly.
    gen_dir = os.path.join(target_workdir, 'gen-{}'.format(self.thrift_generator))
    for path in os.listdir(gen_dir):
      shutil.move(os.path.join(gen_dir, path), target_workdir)
    os.rmdir(gen_dir)

  @memoized_property
  def _thrift_binary(self):
    thrift_binary = ThriftBinary.Factory.scoped_instance(self).create()
    return thrift_binary.path

  @memoized_property
  def _deps(self):
    deps = self.get_options().deps
    return list(self.resolve_deps(deps))

  @memoized_property
  def _service_deps(self):
    service_deps = self.get_options().service_deps
    return list(self.resolve_deps(service_deps)) if service_deps else self._deps

  SERVICE_PARSER = re.compile(r'^\s*service\s+(?:[^\s{]+)')

  def _declares_service(self, source):
    with open(source) as thrift:
      return any(line for line in thrift if self.SERVICE_PARSER.search(line))

  @memoized_property
  def _thrift_cmd(self):
    cmd = [self._thrift_binary]

    def opt_str(item):
      return item[0] if not item[1] else '{}={}'.format(*item)

    gen_opts_map = self.get_options().gen_options_map or {}
    gen_opts = [opt_str(item) for item in gen_opts_map.items()]
    if self.get_options().gen_options:  # Add the deprecated, old options.
      gen_opts.append(self.get_options().gen_options)

    generator_spec = ('{}:{}'.format(self.thrift_generator, ','.join(gen_opts)) if gen_opts
                      else self.thrift_generator)
    cmd.extend(('--gen', generator_spec))

    if self.get_options().strict:
      cmd.append('-strict')
    if self.get_options().level == 'debug':
      cmd.append('-verbose')
    return cmd
