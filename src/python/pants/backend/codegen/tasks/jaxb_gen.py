# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
# just running it on code in our repositories, not on externally acquired data.
from xml.dom.minidom import parse

from pants.backend.codegen.targets.jaxb_library import JaxbLibrary
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.java.distribution.distribution import Distribution
from pants.util.dirutil import safe_mkdir


class JaxbGen(SimpleCodegenTask, NailgunTask):
  """Generates java source files from jaxb schema (.xsd)."""

  def __init__(self, *args, **kwargs):
    """
    :param context: inherited parameter from Task
    :param workdir: inherited parameter from Task
    """
    super(JaxbGen, self).__init__(*args, **kwargs)
    self.gen_langs = set()
    lang = 'java'
    if self.context.products.isrequired(lang):
      self.gen_langs.add(lang)

  def _compile_schema(self, args):
    classpath = Distribution.cached(jdk=True).find_libs(['tools.jar'])
    java_main = 'com.sun.tools.internal.xjc.Driver'
    return self.runjava(classpath=classpath, main=java_main, args=args, workunit_name='xjc')

  @property
  def synthetic_target_type(self):
    return JavaLibrary

  def is_gentarget(self, target):
    return isinstance(target, JaxbLibrary)

  def execute_codegen(self, targets):
    cache = []

    for target in targets:
      output_dir = self.codegen_workdir(target)
      safe_mkdir(output_dir)
      if not isinstance(target, JaxbLibrary):
        raise TaskError('Invalid target type "{class_type}" (expected JaxbLibrary)'
                        .format(class_type=type(target).__name__))

      target_files = []
      for source in target.sources_relative_to_buildroot():
        path_to_xsd = source
        output_package = target.package

        if output_package is None:
          output_package = self._guess_package(source)
        output_package = self._correct_package(output_package)

        output_directory = output_dir
        safe_mkdir(output_directory)
        args = ['-p', output_package, '-d', output_directory, path_to_xsd]
        result = self._compile_schema(args)

        if result != 0:
          raise TaskError('xjc ... exited non-zero ({code})'.format(code=result))
        target_files.append(self._sources_to_be_generated(target.package, path_to_xsd))
      cache.append((target, target_files))

    return cache

  def sources_generated_by_target(self, target):
    to_generate = []
    for source in target.sources_relative_to_buildroot():
      to_generate.extend(self._sources_to_be_generated(target.package, source))
    return to_generate

  @classmethod
  def _guess_package(self, path):
    """Used in genlang to actually invoke the compiler with the proper arguments, and in
    createtarget (via _sources_to_be_generated) to declare what the generated files will be.

    """
    package = ''
    slash = path.rfind(os.path.sep)
    com = path.rfind(os.path.join('', 'com', ''))
    if com < 0 and path.find(os.path.join('com', '')) == 0:
      package = path[:slash]
    elif com >= 0:
      package = path[com:slash]
    package = package.replace(os.path.sep, ' ')
    package = package.strip().replace(' ', '.')
    return package

  @classmethod
  def _correct_package(self, package):
    package = package.replace('/', '.')
    package = re.sub(r'^\.+', '', package)
    package = re.sub(r'\.+$', '', package)
    if re.search(r'\.{2,}', package) is not None:
      raise ValueError('Package name cannot have consecutive periods! ({})'.format(package))
    return package

  @classmethod
  def _sources_to_be_generated(self, package, path):
    """This method (or some variation of it) seems to be common amongst all implementations of
    code-generating tasks.

    As far as I can tell, its purpose is to peek into the relevant schema files and figure out what
    the final output files will be. This is typically implemented with a variety of hacks,
    accompanied by TODO's saying to do it properly in the future (see apache_thrift_gen.py and
    protobuf_gen.py). The implementation in this file does it 'properly' using python's xml parser,
    though I am making some assumptions about how .xsd's are supposed to be formatted, as that is
    not a subject I am particularly informed about.
    """
    doc = parse(path)
    if package is None:
      package = self._guess_package(path)
    package = self._correct_package(package)

    names = []
    for root in doc.childNodes:
      if re.match('.*?:schema$', root.nodeName, re.I) is not None:
        for element in root.childNodes:
          if element.nodeName != '#text' and element.attributes.has_key('name'):
            name = element.attributes['name'].nodeValue
            if len(name) == 0: continue
            # enforce pascal-case class names
            name = name[0:1].upper() + name[1:]
            names.append(name)

    names.append('ObjectFactory')
    outdir = package.replace('.', '/')
    return [os.path.join(outdir, '{}.java'.format(name)) for name in names]
