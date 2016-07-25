# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import pkgutil
import shutil
import subprocess

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.project_info.tasks.ide_gen import IdeGen
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.task.console_task import ConsoleTask
from pants.util import desktop
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir


_TEMPLATE_BASEDIR = 'templates/idea'

# Follow `export.py` for versioning strategy.
IDEA_PLUGIN_VERSION = '0.0.1'


class IdeaPluginGen(IdeGen, ConsoleTask):
  """Invoke IntelliJ Pants plugin (installation required) to create a project.

  The ideal workflow is to programmatically open idea -> select import -> import as pants project -> select project
  path, but IDEA does not have CLI support for "select import" and "import as pants project" once it is opened.

  Therefore, this task takes another approach to embed the target specs into a `iws` workspace file along
  with an skeleton `ipr` project file.

  Sample `iws`:
  ********************************************************
    <?xml version="1.0"?>
    <project version="4">
      <component name="PropertiesComponent">
        <property name="targets" value="[&quot;/Users/me/workspace/pants/testprojects/tests/scala/org/pantsbuild/testproject/cp-directories/::&quot;]" />
        <property name="project_path" value="/Users/me/workspace/pants/testprojects/tests/scala/org/pantsbuild/testproject/cp-directories/" />
      </component>
    </project>
  ********************************************************

  Once pants plugin sees `targets` and `project_path`, it will simulate the import process on and populate the
  existing skeleton project into a Pants project as if user is importing these targets.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super(IdeGen, cls).prepare(options, round_manager)

  @classmethod
  def register_options(cls, register):
    super(IdeaPluginGen, cls).register_options(register)
    # TODO: https://github.com/pantsbuild/pants/issues/3198
    # scala/java-language level should use what Pants already knows.
    register('--open', type=bool, default=True,
             help='Attempts to open the generated project in IDEA.')
    register('--java-encoding', default='UTF-8',
             help='Sets the file encoding for java files in this project.')
    register('--open-with', advanced=True, default=None, recursive=True,
             help='Program used to open the generated IntelliJ project.')

  def __init__(self, *args, **kwargs):
    super(IdeaPluginGen, self).__init__(*args, **kwargs)

    self.open = self.get_options().open

    self.java_encoding = self.get_options().java_encoding
    self.project_template = os.path.join(_TEMPLATE_BASEDIR,
                                         'project-12.mustache')
    self.workspace_template = os.path.join(_TEMPLATE_BASEDIR,
                                           'workspace-12.mustache')

    output_dir = os.path.join(get_buildroot(), ".idea", self.__class__.__name__)
    safe_mkdir(output_dir)

    with temporary_dir(root_dir=output_dir, cleanup=False) as output_project_dir:
      self.gen_project_workdir = output_project_dir
      self.project_filename = os.path.join(self.gen_project_workdir,
                                           '{}.ipr'.format(self.project_name))
      self.workspace_filename = os.path.join(self.gen_project_workdir,
                                             '{}.iws'.format(self.project_name))
      self.intellij_output_dir = os.path.join(self.gen_project_workdir, 'out')

  # TODO: https://github.com/pantsbuild/pants/issues/3198
  # trim it down or refactor together with IdeaGen
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
      debug_port=project.debug_port,
      extra_components=[],
      java_language_level=java_language_level,
    )

    if not self.context.options.target_specs:
      raise TaskError("No targets specified.")

    abs_target_specs = [os.path.join(get_buildroot(), spec) for spec in self.context.options.target_specs]
    configured_workspace = TemplateData(
      targets=json.dumps(abs_target_specs),
      project_path=os.path.join(get_buildroot(), abs_target_specs[0].split(':')[0]),
      idea_plugin_version=IDEA_PLUGIN_VERSION
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
    with temporary_file(cleanup=False) as output:
      generator.write(output)
      return output.name

  def execute(self):
    """Stages IDE project artifacts to a project directory and generates IDE configuration files."""
    # Grab the targets in-play before the context is replaced by `self._prepare_project()` below.
    self._prepare_project()
    ide_file = self.generate_project(self._project)

    if ide_file and self.get_options().open:
      open_with = self.get_options().open_with
      if open_with:
        null = open(os.devnull, 'w')
        subprocess.Popen([open_with, ide_file], stdout=null, stderr=null)
      else:
        try:
          desktop.ui_open(ide_file)
        except desktop.OpenError as e:
          raise TaskError(e)
