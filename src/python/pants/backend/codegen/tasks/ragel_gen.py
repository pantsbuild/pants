# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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


class RagelGen(CodeGen):
  def __init__(self, *args, **kwargs):
    super(RagelGen, self).__init__(*args, **kwargs)

    self._ragel_supportdir = self.context.config.get('ragel-gen', 'supportdir')
    self._ragel_version = self.context.config.get('ragel-gen', 'version', default='6.8')
    self._java_out = os.path.join(self.workdir, 'gen-java')
    self._ragel_binary = None

  @property
  def ragel_binary(self):
    if self._ragel_binary is None:
      self._ragel_binary = BinaryUtil(config=self.context.config).select_binary(
        self._ragel_supportdir,
        self._ragel_version,
        'ragel'
        )
    return self._ragel_binary

  @property
  def javadeps(self):
    return OrderedSet()

  def invalidate_for_files(self):
    return [self.ragel_binary]

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

      args = [self.ragel_binary, lang_flag, '-o', output_file]

      args.append(source)
      self.context.log.debug('Executing: {args}'.format(args=' '.join(args)))
      process = subprocess.Popen(args)
      result = process.wait()
      if result != 0:
        raise TaskError('{binary} ... exited non-zero ({result})'.format(binary=self.ragel_binary, result=result))

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
