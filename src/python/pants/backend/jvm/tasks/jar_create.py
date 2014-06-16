# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import functools
import os

from twitter.common.dirutil import safe_mkdir

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.backend.jvm.tasks.javadoc_gen import javadoc
from pants.backend.jvm.tasks.scaladoc_gen import scaladoc
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.fs.fs import safe_filename
from pants.java.jar.manifest import Manifest


def is_jvm_binary(target):
  return isinstance(target, JvmBinary)


def is_java_library(target):
  return target.has_sources('.java')


def is_scala_library(target):
  return target.has_sources('.scala')


def is_jvm_library(target):
  return (is_java_library(target)
          or is_scala_library(target)
          or (is_jvm_binary(target) and target.has_resources))


def jarname(target, extension='.jar'):
  # TODO(John Sirois): incorporate version
  _, id_, _ = target.get_artifact_info()
  # Cap jar names quite a bit lower than the standard fs limit of 255 characters since these
  # artifacts will often be used outside pants and those uses may manipulate (expand) the jar
  # filenames blindly.
  return safe_filename(id_, extension, max_length=200)


def _abs_and_relative_sources(target):
  abs_source_root = os.path.join(get_buildroot(), target.target_base)
  for source in target.sources_relative_to_source_root():
    yield os.path.join(abs_source_root, source), source


class JarCreate(JarTask):
  """Jars jvm libraries and optionally their sources and their docs."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(JarCreate, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('compressed'), mkflag('compressed', negate=True),
                            dest='jar_create_compressed', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create compressed jars.')

    option_group.add_option(mkflag('classes'), mkflag('classes', negate=True),
                            dest='jar_create_classes', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create class jars.')
    option_group.add_option(mkflag('sources'), mkflag('sources', negate=True),
                            dest='jar_create_sources', default=False,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create source jars.')
    #TODO tdesai: Think about a better way to set defaults per goal basis.
    javadoc_defaults = True if option_group.title.split(':')[0] == 'publish' else False
    option_group.add_option(mkflag('javadoc'), mkflag('javadoc', negate=True),
                            dest='jar_create_javadoc',
                            default=javadoc_defaults,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create javadoc jars.')

  def __init__(self, context, workdir):
    super(JarCreate, self).__init__(context, workdir)

    options = context.options
    products = context.products

    self.compressed = options.jar_create_compressed

    self.jar_classes = options.jar_create_classes or products.isrequired('jars')
    if self.jar_classes:
      self._jar_builder = self.prepare_jar_builder()

    definitely_create_javadoc = options.jar_create_javadoc or products.isrequired('javadoc_jars')
    definitely_dont_create_javadoc = options.jar_create_javadoc is False
    create_javadoc = options.jar_create_javadoc
    if definitely_create_javadoc and definitely_dont_create_javadoc:
      self.context.log.warn('javadoc jars are required but you have requested they not be created, '
                            'creating anyway')
    self.jar_javadoc = (True if definitely_create_javadoc else
                        False if definitely_dont_create_javadoc else
                        create_javadoc)
    if self.jar_javadoc:
      products.require(javadoc.product_type)
      products.require(scaladoc.product_type)

    self.jar_sources = products.isrequired('source_jars') or options.jar_create_sources

    self._jars = {}

  def execute(self):
    safe_mkdir(self.workdir)

    def jar_targets(predicate):
      return self.context.targets(predicate)

    def add_genjar(typename, target, name):
      self.context.products.get(typename).add(target, self.workdir).append(name)

    with self.context.new_workunit(name='jar-create', labels=[WorkUnit.MULTITOOL]):
      # TODO(Tejal Desai) pantsbuild/pants/65: Avoid creating 2 jars with java sources for
      # scala_library with java_sources. Currently publish fails fast if scala_library owning
      # java sources pointed by java_library target also provides an artifact. However, jar_create
      # ends up creating 2 jars one scala and other java both including the java_sources.
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
    with self.open_jar(path, overwrite=True, compressed=self.compressed) as jar:
      yield jar

  def _jar(self, jvm_targets, add_genjar):
    for target in jvm_targets:
      jar_name = jarname(target)
      jar_path = os.path.join(self.workdir, jar_name)
      with self.create_jar(target, jar_path) as jarfile:
        if self._jar_builder.add_target(jarfile, target):
          add_genjar(target, jar_name)

  def sourcejar(self, jvm_targets, add_genjar):
    for target in jvm_targets:
      jar_name = jarname(target, '-sources.jar')
      add_genjar(target, jar_name)
      jar_path = os.path.join(self.workdir, jar_name)
      with self.create_jar(target, jar_path) as jar:
        for abs_source, rel_source in _abs_and_relative_sources(target):
          jar.write(abs_source, rel_source)

        # TODO(Tejal Desai): pantsbuild/pants/65 Remove java_sources attribute for ScalaLibrary
        if isinstance(target, ScalaLibrary):
          for java_source_target in target.java_sources:
            for abs_source, rel_source in _abs_and_relative_sources(java_source_target):
              jar.write(abs_source, rel_source)

        if target.has_resources:
          for resource_target in target.resources:
            for abs_source, rel_source in _abs_and_relative_sources(resource_target):
              jar.write(abs_source, rel_source)

  def javadocjar(self, java_targets, genmap, add_genjar):
    for target in java_targets:
      generated = genmap.get(target)
      if generated:
        jar_name = jarname(target, '-javadoc.jar')
        add_genjar(target, jar_name)
        jar_path = os.path.join(self.workdir, jar_name)
        with self.create_jar(target, jar_path) as jar:
          for basedir, javadocfiles in generated.items():
            for javadocfile in javadocfiles:
              jar.write(os.path.join(basedir, javadocfile), javadocfile)
