# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import subprocess

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir_for

from pants.backend.codegen.targets.java_ragel_library import JavaRagelLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binary_util import BinaryUtil
from pants.util.memo import memoized_property


class RagelGen(CodeGen):
  @classmethod
  def global_subsystems(cls):
    return super(RagelGen, cls).global_subsystems() + (BinaryUtil.Factory,)

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

  @property
  def javadeps(self):
    return OrderedSet()

  def is_gentarget(self, target):
    return isinstance(target, JavaRagelLibrary)

  def is_forced(self, lang):
    return lang == 'java'

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def genlang(self, lang, targets):
    if lang != 'java':
      raise TaskError('Unrecognized ragel gen lang: {lang}'.format(lang=lang))
    sources = self._calculate_sources(targets)

    output_dir = self._java_out
    lang_flag = '-J'

    for source in sources:
      output_file = os.path.join(output_dir, calculate_genfile(source))
      safe_mkdir_for(output_file)

      args = [self.ragel_binary, lang_flag, '-o', output_file, source]

      self.context.log.debug('Executing: {args}'.format(args=' '.join(args)))
      process = subprocess.Popen(args)
      result = process.wait()
      if result != 0:
        raise TaskError('{binary} ... exited non-zero ({result})'.format(binary=self.ragel_binary,
                                                                         result=result))

  def _calculate_sources(self, targets):
    sources = set()

    def collect_sources(target):
      if self.is_gentarget(target):
        for source in target.sources_relative_to_buildroot():
          sources.add(os.path.join(get_buildroot(), source))

    for target in targets:
      target.walk(collect_sources)
    return sources

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized ragel gen lang: {lang}'.format(lang=lang))

  def _create_java_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(get_buildroot(), target.target_base, source)
      genfile = calculate_genfile(path)
      genfiles.append(os.path.join(self._java_out, genfile))

    spec_path = os.path.relpath(self._java_out, get_buildroot())
    spec = '{spec_path}:{name}'.format(spec_path=spec_path, name=target.id)
    address = SyntheticAddress.parse(spec=spec)
    tgt = self.context.add_new_target(address,
                                      JavaRagelLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      provides=target.provides,
                                      dependencies=self.javadeps,
                                      excludes=target.payload.excludes)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt


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
  return "{package}/{cls}.java".format (package=package.replace(".", os.path.sep), cls=classname)


def calculate_genfile(path):
  package, classname = calculate_class_and_package(path)
  return get_filename(package, classname)
