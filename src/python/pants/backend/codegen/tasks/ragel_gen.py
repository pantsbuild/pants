# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import subprocess

from pants.backend.codegen.targets.java_ragel_library import JavaRagelLibrary
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil
from pants.util.dirutil import safe_mkdir_for
from pants.util.memo import memoized_property


class RagelGen(SimpleCodegenTask):
  @classmethod
  def subsystem_dependencies(cls):
    return super(RagelGen, cls).subsystem_dependencies() + (BinaryUtil.Factory,)

  @classmethod
  def register_options(cls, register):
    super(RagelGen, cls).register_options(register)
    register('--supportdir', default='bin/ragel', advanced=True,
             help='The path to find the ragel binary.  Used as part of the path to lookup the'
                  'tool with --pants-support-baseurls and --pants_bootstrapdir.')

    # We take the cautious approach here and assume a version bump will always correspond to
    # changes in ragel codegen products.
    register('--version', default='6.9', advanced=True, fingerprint=True,
             help='The version of ragel to use.  Used as part of the path to lookup the'
                  'tool with --pants-support-baseurls and --pants-bootstrapdir')

  def __init__(self, *args, **kwargs):
    super(RagelGen, self).__init__(*args, **kwargs)
    self._java_out = os.path.join(self.workdir, 'gen-java')

  @memoized_property
  def ragel_binary(self):
    binary_util = BinaryUtil.Factory.create()
    return binary_util.select_binary(self.get_options().supportdir,
                                     self.get_options().version,
                                     'ragel')

  def synthetic_target_type(self, target):
    return JavaLibrary

  def is_gentarget(self, target):
    return isinstance(target, JavaRagelLibrary)

  def execute_codegen(self, target, target_workdir):
    for source in target.sources_relative_to_buildroot():
      abs_source = os.path.join(get_buildroot(), source)

      output_file = os.path.join(target_workdir, calculate_genfile(abs_source))
      safe_mkdir_for(output_file)

      args = [self.ragel_binary, '-J', '-o', output_file, abs_source]

      self.context.log.debug('Executing: {args}'.format(args=' '.join(args)))
      process = subprocess.Popen(args)
      result = process.wait()
      if result != 0:
        raise TaskError('{binary} ... exited non-zero ({result})'
                        .format(binary=self.ragel_binary, result=result))


def calculate_class_and_package(path):
  package, classname = None, None
  with open(path, 'r') as ragel:
    for line in ragel.readlines():
      line = line.strip()
      package_match = re.match(r'^package ([.a-zA-Z0-9]+);', line)
      if package_match:
        if package:
          raise TaskError('Multiple package declarations in {path}'.format(path=path))
        package = package_match.group(1)
      class_match = re.match(r'^public class ([A-Za-z0-9_]+).*', line)
      if class_match:
        if classname:
          raise TaskError('Multiple class declarations in {path}'.format(path=path))
        classname = class_match.group(1)

  if not package:
    raise TaskError('Missing package declaration in {path}'.format(path=path))
  if not classname:
    raise TaskError('Missing class declaration in {path}'.format(path=path))
  return package, classname


def get_filename(package, classname):
  return "{package}/{cls}.java".format(package=package.replace(".", os.path.sep), cls=classname)


def calculate_genfile(path):
  package, classname = calculate_class_and_package(path)
  return get_filename(package, classname)
