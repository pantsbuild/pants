# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import pkgutil
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.project_info.tasks.ide_gen import IdeGen
from pants.base.build_environment import get_buildroot
from pants.base.generator import Generator, TemplateData
from pants.util.dirutil import safe_open


_TEMPLATE_BASEDIR = os.path.join('templates', 'ensime')
_DEFAULT_PROJECT_DIR = './.pants.d/ensime/project'

_SCALA_VERSION_DEFAULT = '2.10'
_SCALA_VERSIONS = {
  '2.8': 'Scala 2.8',
  '2.9': 'Scala 2.9',
  _SCALA_VERSION_DEFAULT: 'Scala 2.10',
  '2.10-virt': 'Scala 2.10 virtualized'
}


class EnsimeGen(IdeGen):

  @classmethod
  def register_options(cls, register):
    super(EnsimeGen, cls).register_options(register)
    register('--scala-language-level',
             choices=_SCALA_VERSIONS.keys(), default=_SCALA_VERSION_DEFAULT,
             help='Set the scala language level used for Ensime linting.')

  def __init__(self, *args, **kwargs):
    super(EnsimeGen, self).__init__(*args, **kwargs)

    self.scala_language_level = _SCALA_VERSIONS.get(
      self.get_options().scala_language_level, None)
    self.project_template = os.path.join(_TEMPLATE_BASEDIR, 'ensime.mustache')
    self.project_filename = os.path.join(self.cwd, '.ensime')
    self.ensime_output_dir = os.path.join(self.gen_project_workdir, 'out')

  def generate_project(self, project):
    def linked_folder_id(source_set):
      return source_set.source_base.replace(os.path.sep, '.')

    def base_path(source_set):
      return os.path.join(source_set.root_dir, source_set.source_base)

    def create_source_base_template(source_set):
      source_base = base_path(source_set)
      return source_base, TemplateData(
        id=linked_folder_id(source_set),
        path=source_base
      )

    source_bases = dict(map(create_source_base_template, project.sources))

    def create_source_template(base_id, includes=None, excludes=None):
      return TemplateData(
        base=base_id,
        includes='|'.join(OrderedSet(includes)) if includes else None,
        excludes='|'.join(OrderedSet(excludes)) if excludes else None,
      )

    def create_sourcepath(base_id, sources):
      def normalize_path_pattern(path):
        return '{}/'.format(path) if not path.endswith('/') else path

      includes = [normalize_path_pattern(src_set.path) for src_set in sources if src_set.path]
      excludes = []
      for source_set in sources:
        excludes.extend(normalize_path_pattern(exclude) for exclude in source_set.excludes)

      return create_source_template(base_id, includes, excludes)

    source_sets = defaultdict(OrderedSet)  # base_id -> source_set
    for source_set in project.sources:
      source_sets[linked_folder_id(source_set)].add(source_set)
    sourcepaths = [create_sourcepath(base_id, sources) for base_id, sources in source_sets.items()]

    libs = []

    def add_jarlibs(classpath_entries):
      for classpath_entry in classpath_entries:
        libs.append((classpath_entry.jar, classpath_entry.source_jar))
    add_jarlibs(project.internal_jars)
    add_jarlibs(project.external_jars)

    scala = TemplateData(
      language_level=self.scala_language_level,
      compiler_classpath=project.scala_compiler_classpath
    )

    outdir = os.path.abspath(self.ensime_output_dir)
    if not os.path.exists(outdir):
      os.makedirs(outdir)

    configured_project = TemplateData(
      name=self.project_name,
      java=TemplateData(
        jdk=self.java_jdk,
        language_level=('1.{}'.format(self.java_language_level))
      ),
      scala=scala,
      source_bases=source_bases.values(),
      sourcepaths=sourcepaths,
      has_tests=project.has_tests,
      internal_jars=[cp_entry.jar for cp_entry in project.internal_jars],
      internal_source_jars=[cp_entry.source_jar for cp_entry in project.internal_jars
                            if cp_entry.source_jar],
      external_jars=[cp_entry.jar for cp_entry in project.external_jars],
      external_javadoc_jars=[cp_entry.javadoc_jar for cp_entry in project.external_jars
                             if cp_entry.javadoc_jar],
      external_source_jars=[cp_entry.source_jar for cp_entry in project.external_jars
                            if cp_entry.source_jar],
      libs=libs,
      outdir=os.path.relpath(outdir, get_buildroot()),
    )

    def apply_template(output_path, template_relpath, **template_data):
      with safe_open(output_path, 'w') as output:
        Generator(pkgutil.get_data(__name__, template_relpath), **template_data).write(output)

    apply_template(self.project_filename, self.project_template, project=configured_project)
    print('\nGenerated ensime project at {}{}'.format(self.gen_project_workdir, os.sep))
