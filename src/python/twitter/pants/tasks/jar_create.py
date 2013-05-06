# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import functools
import os

from contextlib import contextmanager
from zipfile import ZIP_STORED, ZIP_DEFLATED

from twitter.common.dirutil import safe_mkdir

from twitter.pants import (
    get_buildroot,
    has_resources,
    has_sources,
    is_exported)
from twitter.pants.java import open_jar
from twitter.pants.tasks import Task, TaskError


def is_java(target):
  return has_sources(target, '.java')


def is_jvm(target):
  return is_java(target) or has_sources(target, '.scala')


def is_idl(target):
  # TODO(Phil Hom): can be changed to is_codegen when previous hackweek thrift download hacks are
  # removed
  return is_exported(target) and has_sources(target, '.thrift')


def jarname(target):
  # TODO(John Sirois): incorporate version
  _, id, _ = target._get_artifact_info()
  return id


class JarCreate(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="jar_create_outdir",
                            help="Emit jars in to this directory.")

    option_group.add_option(mkflag("compressed"), mkflag("compressed", negate=True),
                            dest="jar_create_compressed", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create compressed jars.")

    option_group.add_option(mkflag("transitive"), mkflag("transitive", negate=True),
                            dest="jar_create_transitive", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create jars for the transitive closure of internal "
                                 "targets reachable from the roots specified on the command line.")

    option_group.add_option(mkflag("classes"), mkflag("classes", negate=True),
                            dest="jar_create_classes", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create class jars.")
    option_group.add_option(mkflag("sources"), mkflag("sources", negate=True),
                            dest="jar_create_sources", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create source jars.")
    option_group.add_option(mkflag("javadoc"), mkflag("javadoc", negate=True),
                            dest="jar_create_javadoc", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create javadoc jars.")
    option_group.add_option(mkflag("idl"), mkflag("idl", negate=True),
                            dest="jar_create_idl", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create Thrift jars.")

  def __init__(self, context):
    Task.__init__(self, context)

    options = context.options
    products = context.products

    self._output_dir = options.jar_create_outdir or context.config.get('jar-create', 'workdir')
    self.transitive = options.jar_create_transitive
    self.confs = context.config.getlist('jar-create', 'confs')
    self.compression = ZIP_DEFLATED if options.jar_create_compressed else ZIP_STORED

    self.jar_classes = products.isrequired('jars') or options.jar_create_classes
    if self.jar_classes:
      products.require('classes')

    self.jar_idl = products.isrequired('idl_jars') or options.jar_create_idl
    if self.jar_idl:
      products.require('idl')

    self.jar_javadoc = products.isrequired('javadoc_jars') or options.jar_create_javadoc
    if self.jar_javadoc:
      products.require('javadoc')

    self.jar_sources = products.isrequired('source_jars') or options.jar_create_sources

    self._jars = {}

  def execute(self, targets):
    safe_mkdir(self._output_dir)

    def jar_targets(predicate):
      return filter(predicate, (targets if self.transitive else self.context.target_roots))

    def add_genjar(typename, target, name):
      if self.context.products.isrequired(typename):
        self.context.products.get(typename).add(target, self._output_dir).append(name)

    if self.jar_classes:
      self.jar(jar_targets(is_jvm),
               self.context.products.get('classes'),
               functools.partial(add_genjar, 'jars'))

    if self.jar_idl:
      self.idljar(jar_targets(is_idl), functools.partial(add_genjar, 'idl_jars'))

    if self.jar_sources:
      self.sourcejar(jar_targets(is_jvm), functools.partial(add_genjar, 'source_jars'))

    if self.jar_javadoc:
      self.javadocjar(jar_targets(is_java),
                      self.context.products.get('javadoc'),
                      functools.partial(add_genjar, 'javadoc_jars'))

  @contextmanager
  def create_jar(self, target, path):
    existing = self._jars.setdefault(path, target)
    if target != existing:
      raise TaskError('Duplicate name: target %s tried to write %s already mapped to target %s' % (
        target, path, existing
      ))
    self._jars[path] = target
    with open_jar(path, 'w', compression=self.compression) as jar:
      yield jar

  def jar(self, jvm_targets, genmap, add_genjar):
    for target in jvm_targets:
      generated = genmap.get(target)
      if generated or has_resources(target):
        jar_name = '%s.jar' % jarname(target)
        add_genjar(target, jar_name)
        jar_path = os.path.join(self._output_dir, jar_name)
        with self.create_jar(target, jar_path) as zip:
          if generated:
            for basedir, classfiles in generated.items():
              for classfile in classfiles:
                zip.write(os.path.join(basedir, classfile), classfile)

          if has_resources(target):
            resources_genmap = self.context.products.get('resources')
            if resources_genmap:
              for resources in target.resources:
                resource_map = resources_genmap.get(resources)
                if resource_map:
                  for basedir, files in resource_map.items():
                    for resource in files:
                      zip.write(os.path.join(basedir, resource), resource)

  def idljar(self, jvm_targets, add_genjar):
    for target in jvm_targets:
      jar_name = '%s-idl.jar' % jarname(target)
      add_genjar(target, jar_name)
      jar_path = os.path.join(self._output_dir, jar_name)
      with self.create_jar(target, jar_path) as zh:
        for source in target.sources:
          zh.write(os.path.join(target.target_base, source), source)

  def sourcejar(self, jvm_targets, add_genjar):
    for target in jvm_targets:
      jar_name = '%s-sources.jar' % jarname(target)
      add_genjar(target, jar_name)
      jar_path = os.path.join(self._output_dir, jar_name)
      with self.create_jar(target, jar_path) as zip:
        for source in target.sources:
          zip.write(os.path.join(target.target_base, source), source)

        if has_resources(target):
          for resources in target.resources:
            for resource in resources.sources:
              zip.write(os.path.join(get_buildroot(), resources.target_base, resource), resource)

  def javadocjar(self, java_targets, genmap, add_genjar):
    for target in java_targets:
      generated = genmap.get(target)
      if generated:
        jar_name = '%s-javadoc.jar' % jarname(target)
        add_genjar(target, jar_name)
        jar_path = os.path.join(self._output_dir, jar_name)
        with self.create_jar(target, jar_path) as zip:
          for basedir, javadocfiles in generated.items():
            for javadocfile in javadocfiles:
              zip.write(os.path.join(basedir, javadocfile), javadocfile)
