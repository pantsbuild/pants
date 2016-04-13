# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import pkgutil
import shutil
import tempfile

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.project_info.tasks.ide_gen import IdeGen
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.generator import Generator, TemplateData
from pants.binaries import binary_util
from pants.task.console_task import ConsoleTask
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir


PROJECT_OUTPUT_MESSAGE = 'Generated IntelliJ project in'

_TEMPLATE_BASEDIR = 'templates/idea'


_VERSIONS = {
  '9': '12',  # 9 and 12 are ipr/iml compatible
  '10': '12',  # 10 and 12 are ipr/iml compatible
  '11': '12',  # 11 and 12 are ipr/iml compatible
  '12': '12'
}


_SCALA_VERSION_DEFAULT = '2.9'
_SCALA_VERSIONS = {
  '2.8': 'Scala 2.8',
  _SCALA_VERSION_DEFAULT: 'Scala 2.9',
  '2.10': 'Scala 2.10',
  '2.10-virt': 'Scala 2.10 virtualized'
}


class PluginGen(IdeGen, ConsoleTask):
  """Invoke an IntelliJ Pants plugin to create a project from the given targets."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(IdeGen, cls).prepare(options, round_manager)

  @classmethod
  def register_options(cls, register):
    super(PluginGen, cls).register_options(register)
    register('--version', choices=sorted(list(_VERSIONS.keys())), default='11',
             help='The IntelliJ IDEA version the project config should be generated for.')
    register('--open', action='store_true', default=True,
             help='Attempts to open the generated project in IDEA.')
    register('--scala-language-level',
             choices=_SCALA_VERSIONS.keys(), default=_SCALA_VERSION_DEFAULT,
             help='Set the scala language level used for IDEA linting.')
    register('--java-encoding', default='UTF-8',
             help='Sets the file encoding for java files in this project.')

  def __init__(self, *args, **kwargs):
    super(PluginGen, self).__init__(*args, **kwargs)

    self.open = self.get_options().open

    self.scala_language_level = _SCALA_VERSIONS.get(
      self.get_options().scala_language_level, None)

    self.java_encoding = self.get_options().java_encoding

    idea_version = _VERSIONS[self.get_options().version]
    self.project_template = os.path.join(_TEMPLATE_BASEDIR,
                                         'project-{}.mustache'.format(idea_version))
    self.workspace_template = os.path.join(_TEMPLATE_BASEDIR,
                                        'workspace-{}.mustache'.format(idea_version))

    output_dir = os.path.join(get_buildroot(), ".idea", "idea-plugin")
    safe_mkdir(output_dir)

    with temporary_dir(root_dir=output_dir, cleanup=False) as output_project_dir:
      self.gen_project_workdir = output_project_dir

      self.project_filename = os.path.join(self.gen_project_workdir,
                                           '{}.ipr'.format(self.project_name))
      self.workspace_filename = os.path.join(self.gen_project_workdir,
                                          '{}.iws'.format(self.project_name))
      self.intellij_output_dir = os.path.join(self.gen_project_workdir, 'out')

  def generate_project(self, project):
    def create_content_root(source_set):
      root_relative_path = os.path.join(source_set.source_base, source_set.path) \
                           if source_set.path else source_set.source_base
      if source_set.resources_only:
        if source_set.is_test:
          content_type = 'java-test-resource'
        else:
          content_type = 'java-resource'
      else:
        content_type = ''

      sources = TemplateData(
        path=root_relative_path,
        package_prefix=source_set.path.replace('/', '.') if source_set.path else None,
        is_test=source_set.is_test,
        content_type=content_type
      )

      return TemplateData(
        path=root_relative_path,
        sources=[sources],
        exclude_paths=[os.path.join(source_set.source_base, x) for x in source_set.excludes],
      )

    content_roots = [create_content_root(source_set) for source_set in project.sources]
    if project.has_python:
      content_roots.extend(create_content_root(source_set) for source_set in project.py_sources)

    scala = None
    if project.has_scala:
      scala = TemplateData(
        language_level=self.scala_language_level,
      )

    java_language_level = None
    for target in project.targets:
      if isinstance(target, JvmTarget):
        if java_language_level is None or java_language_level < target.platform.source_level:
          java_language_level = target.platform.source_level
    if java_language_level is not None:
      java_language_level = 'JDK_{0}_{1}'.format(*java_language_level.components[:2])

    outdir = os.path.abspath(self.intellij_output_dir)
    if not os.path.exists(outdir):
      os.makedirs(outdir)

    scm = get_scm()
    configured_project = TemplateData(
      root_dir=get_buildroot(),
      outdir=outdir,
      git_root=scm.worktree,
      java=TemplateData(
        encoding=self.java_encoding,
        jdk=self.java_jdk,
        language_level='JDK_1_{}'.format(self.java_language_level)
      ),
      resource_extensions=list(project.resource_extensions),
      scala=scala,
      debug_port=project.debug_port,
      extra_components=[],
      java_language_level=java_language_level,
    )

    abs_target_specs = [os.path.join(get_buildroot(), spec) for spec in self.context.options.target_specs]
    configured_workspace = TemplateData(
      targets=json.dumps(abs_target_specs),
      project_path=os.path.join(get_buildroot(), self.context.options.target_specs.__iter__().next().split(':')[0])
    )

    # Generate (without merging in any extra components).
    safe_mkdir(os.path.abspath(self.intellij_output_dir))

    ipr = self._generate_to_tempfile(
        Generator(pkgutil.get_data(__name__, self.project_template), project=configured_project))
    iws = self._generate_to_tempfile(
        Generator(pkgutil.get_data(__name__, self.workspace_template), workspace=configured_workspace))

    self._outstream.write(self.gen_project_workdir)

    shutil.move(ipr, self.project_filename)
    shutil.move(iws, self.workspace_filename)
    return self.project_filename

  def _generate_to_tempfile(self, generator):
    """Applies the specified generator to a temp file and returns the path to that file.
    We generate into a temp file so that we don't lose any manual customizations on error."""
    (output_fd, output_path) = tempfile.mkstemp()
    with os.fdopen(output_fd, 'w') as output:
      generator.write(output)
    return output_path

  def execute(self):
    """Stages IDE project artifacts to a project directory and generates IDE configuration files."""
    # Grab the targets in-play before the context is replaced by `self._prepare_project()` below.
    self._prepare_project()
    idefile = self.generate_project(self._project)

    if idefile and self.get_options().open:
      binary_util.ui_open(idefile)
