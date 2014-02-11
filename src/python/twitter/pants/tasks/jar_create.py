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

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.fs import safe_filename
from twitter.pants.java.jar import open_jar
from twitter.pants.targets import JvmBinary

from .javadoc_gen import javadoc
from .scaladoc_gen import scaladoc

from . import Task, TaskError


DEFAULT_CONFS = ['default']


def is_binary(target):
  return isinstance(target, JvmBinary)


def is_java_library(target):
  return target.has_sources('.java') and not is_binary(target)


def is_scala_library(target):
  return target.has_sources('.scala') and not is_binary(target)


def is_jvm_library(target):
  return is_java_library(target) or is_scala_library(target)


def jarname(target, extension='.jar'):
  # TODO(John Sirois): incorporate version
  _, id_, _ = target.get_artifact_info()
  # Cap jar names quite a bit lower than the standard fs limit of 255 characters since these
  # artifacts will often be used outside pants and those uses may manipulate (expand) the jar
  # filenames blindly.
  return safe_filename(id_, extension, max_length=200)


class JarCreate(Task):
  """Jars jvm libraries and optionally their sources and their docs."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('outdir'), dest='jar_create_outdir',
                            help='Emit jars in to this directory.')

    option_group.add_option(mkflag('compressed'), mkflag('compressed', negate=True),
                            dest='jar_create_compressed', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create compressed jars.')

    option_group.add_option(mkflag('transitive'), mkflag('transitive', negate=True),
                            dest='jar_create_transitive', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create jars for the transitive closure of internal '
                                 'targets reachable from the roots specified on the command line.')

    option_group.add_option(mkflag('classes'), mkflag('classes', negate=True),
                            dest='jar_create_classes', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create class jars.')
    option_group.add_option(mkflag('sources'), mkflag('sources', negate=True),
                            dest='jar_create_sources', default=False,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create source jars.')
    option_group.add_option(mkflag('javadoc'), mkflag('javadoc', negate=True),
                            dest='jar_create_javadoc', default=False,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create javadoc jars.')

  def __init__(self, context, jar_javadoc=False):
    Task.__init__(self, context)

    options = context.options
    products = context.products

    self._output_dir = (options.jar_create_outdir or
                        self.get_workdir(section='jar-create', workdir='jars'))
    self.transitive = options.jar_create_transitive
    self.confs = context.config.getlist('jar-create', 'confs', default=DEFAULT_CONFS)
    self.compression = ZIP_DEFLATED if options.jar_create_compressed else ZIP_STORED

    self.jar_classes = options.jar_create_classes or products.isrequired('jars')
    if self.jar_classes:
      products.require_data('classes_by_target')
      products.require_data('resources_by_target')

    definitely_create_javadoc = options.jar_create_javadoc or products.isrequired('javadoc_jars')
    definitely_dont_create_javadoc = options.jar_create_javadoc is False
    create_javadoc = jar_javadoc and options.jar_create_javadoc is None
    if definitely_create_javadoc and definitely_dont_create_javadoc:
      self.context.log.warn('javadoc jars are required but you have requested they not be created, '
                            'creating anyway')
    self.jar_javadoc = (True  if definitely_create_javadoc      else
                        False if definitely_dont_create_javadoc else
                        create_javadoc)
    if self.jar_javadoc:
      products.require(javadoc.product_type)
      products.require(scaladoc.product_type)

    self.jar_sources = products.isrequired('source_jars') or options.jar_create_sources

    self._jars = {}

  def execute(self, targets):
    safe_mkdir(self._output_dir)

    def jar_targets(predicate):
      return filter(predicate, (targets if self.transitive else self.context.target_roots))

    def add_genjar(typename, target, name):
      self.context.products.get(typename).add(target, self._output_dir).append(name)

    if self.jar_classes:
      self._jar(jar_targets(is_jvm_library), functools.partial(add_genjar, 'jars'))

    if self.jar_sources:
      self.sourcejar(jar_targets(is_jvm_library), functools.partial(add_genjar, 'source_jars'))

    if self.jar_javadoc:
      javadoc_add_genjar = functools.partial(add_genjar, 'javadoc_jars')
      self.javadocjar(jar_targets(is_java_library),
                      self.context.products.get(javadoc.product_type),
                      javadoc_add_genjar)
      self.javadocjar(jar_targets(is_scala_library),
                      self.context.products.get(scaladoc.product_type),
                      javadoc_add_genjar)

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

  def _jar(self, jvm_targets, add_genjar):
    classes_by_target = self.context.products.get_data('classes_by_target')
    resources_by_target = self.context.products.get_data('resources_by_target')

    for target in jvm_targets:
      target_classes = classes_by_target.get(target)

      target_resources = []
      if target.has_resources:
        target_resources.extend(resources_by_target.get(r) for r in target.resources)

      if target_classes or target_resources:
        jar_name = jarname(target)
        add_genjar(target, jar_name)
        jar_path = os.path.join(self._output_dir, jar_name)
        with self.create_jar(target, jar_path) as jarfile:
          def add_to_jar(target_products):
            if target_products:
              for root, products in target_products.rel_paths():
                for prod in products:
                  jarfile.write(os.path.join(root, prod), prod)
          add_to_jar(target_classes)
          for resources_target in target_resources:
            add_to_jar(resources_target)

  def sourcejar(self, jvm_targets, add_genjar):
    for target in jvm_targets:
      jar_name = jarname(target, '-sources.jar')
      add_genjar(target, jar_name)
      jar_path = os.path.join(self._output_dir, jar_name)
      with self.create_jar(target, jar_path) as jar:
        for source in target.sources:
          jar.write(os.path.join(get_buildroot(), target.target_base, source), source)

        if target.has_resources:
          for resources in target.resources:
            for resource in resources.sources:
              jar.write(os.path.join(get_buildroot(), resources.target_base, resource), resource)

  def javadocjar(self, java_targets, genmap, add_genjar):
    for target in java_targets:
      generated = genmap.get(target)
      if generated:
        jar_name = jarname(target, '-javadoc.jar')
        add_genjar(target, jar_name)
        jar_path = os.path.join(self._output_dir, jar_name)
        with self.create_jar(target, jar_path) as jar:
          for basedir, javadocfiles in generated.items():
            for javadocfile in javadocfiles:
              jar.write(os.path.join(basedir, javadocfile), javadocfile)
