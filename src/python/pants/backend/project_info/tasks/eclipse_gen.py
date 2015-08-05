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
from pants.util.dirutil import safe_delete, safe_mkdir, safe_open


_TEMPLATE_BASEDIR = os.path.join('templates', 'eclipse')


_VERSIONS = {
  '3.5': '3.7',  # 3.5-3.7 are .project/.classpath compatible
  '3.6': '3.7',
  '3.7': '3.7',
}


_SETTINGS = (
  'org.eclipse.core.resources.prefs',
  'org.eclipse.jdt.ui.prefs',
)


class EclipseGen(IdeGen):

  @classmethod
  def register_options(cls, register):
    super(EclipseGen, cls).register_options(register)
    register('--version', choices=sorted(list(_VERSIONS.keys())), default='3.6',
             help='The Eclipse version the project configuration should be generated for.')

  def __init__(self, *args, **kwargs):
    super(EclipseGen, self).__init__(*args, **kwargs)

    version = _VERSIONS[self.get_options().version]
    self.project_template = os.path.join(_TEMPLATE_BASEDIR, 'project-{}.mustache'.format(version))
    self.classpath_template = os.path.join(_TEMPLATE_BASEDIR, 'classpath-{}.mustache'.format(version))
    self.apt_template = os.path.join(_TEMPLATE_BASEDIR, 'factorypath-{}.mustache'.format(version))
    self.pydev_template = os.path.join(_TEMPLATE_BASEDIR, 'pydevproject-{}.mustache'.format(version))
    self.debug_template = os.path.join(_TEMPLATE_BASEDIR, 'debug-launcher-{}.mustache'.format(version))
    self.coreprefs_template = os.path.join(_TEMPLATE_BASEDIR,
                                           'org.eclipse.jdt.core.prefs-{}.mustache'.format(version))

    self.project_filename = os.path.join(self.cwd, '.project')
    self.classpath_filename = os.path.join(self.cwd, '.classpath')
    self.apt_filename = os.path.join(self.cwd, '.factorypath')
    self.pydev_filename = os.path.join(self.cwd, '.pydevproject')
    self.coreprefs_filename = os.path.join(self.cwd, '.settings', 'org.eclipse.jdt.core.prefs')

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
    if project.has_python:
      source_bases.update(map(create_source_base_template, project.py_sources))
      source_bases.update(map(create_source_base_template, project.py_libs))

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

    pythonpaths = []
    if project.has_python:
      for source_set in project.py_sources:
        pythonpaths.append(create_source_template(linked_folder_id(source_set)))
      for source_set in project.py_libs:
        lib_path = source_set.path if source_set.path.endswith('.egg') else '{}/'.format(source_set.path)
        pythonpaths.append(create_source_template(linked_folder_id(source_set),
                                                  includes=[lib_path]))

    configured_project = TemplateData(
      name=self.project_name,
      java=TemplateData(
        jdk=self.java_jdk,
        language_level=('1.{}'.format(self.java_language_level))
      ),
      python=project.has_python,
      scala=project.has_scala and not project.skip_scala,
      source_bases=source_bases.values(),
      pythonpaths=pythonpaths,
      debug_port=project.debug_port,
    )

    outdir = os.path.abspath(os.path.join(self.gen_project_workdir, 'bin'))
    safe_mkdir(outdir)

    source_sets = defaultdict(OrderedSet)  # base_id -> source_set
    for source_set in project.sources:
      source_sets[linked_folder_id(source_set)].add(source_set)
    sourcepaths = [create_sourcepath(base_id, sources) for base_id, sources in source_sets.items()]

    libs = list(project.internal_jars)
    libs.extend(project.external_jars)

    configured_classpath = TemplateData(
      sourcepaths=sourcepaths,
      has_tests=project.has_tests,
      libs=libs,
      scala=project.has_scala,

      # Eclipse insists the outdir be a relative path unlike other paths
      outdir=os.path.relpath(outdir, get_buildroot()),
    )

    def apply_template(output_path, template_relpath, **template_data):
      with safe_open(output_path, 'w') as output:
        Generator(pkgutil.get_data(__name__, template_relpath), **template_data).write(output)

    apply_template(self.project_filename, self.project_template, project=configured_project)
    apply_template(self.classpath_filename, self.classpath_template, classpath=configured_classpath)
    apply_template(os.path.join(self.gen_project_workdir,
                                'Debug on port {}.launch'.format(project.debug_port)),
                   self.debug_template, project=configured_project)
    apply_template(self.coreprefs_filename, self.coreprefs_template, project=configured_project)

    for resource in _SETTINGS:
      with safe_open(os.path.join(self.cwd, '.settings', resource), 'w') as prefs:
        prefs.write(pkgutil.get_data(__name__, os.path.join(_TEMPLATE_BASEDIR, resource)))

    factorypath = TemplateData(
      project_name=self.project_name,

      # The easiest way to make sure eclipse sees all annotation processors is to put all libs on
      # the apt factorypath - this does not seem to hurt eclipse performance in any noticeable way.
      jarpaths=libs
    )
    apply_template(self.apt_filename, self.apt_template, factorypath=factorypath)

    if project.has_python:
      apply_template(self.pydev_filename, self.pydev_template, project=configured_project)
    else:
      safe_delete(self.pydev_filename)

    print('\nGenerated project at {}{}'.format(self.gen_project_workdir, os.sep))
