# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.rpmbuild.targets.remote_rpm_source import RemoteRpmSource
from pants.contrib.rpmbuild.targets.rpm_package import RpmPackageTarget
from pants.contrib.rpmbuild.tasks.remote_rpm_source_task import RemoteRpmSourceTask
from pants.contrib.rpmbuild.tasks.rpmbuild_task import RpmbuildTask


def build_file_aliases():
  return BuildFileAliases(
    targets={
      RemoteRpmSource.alias(): RemoteRpmSource,
      RpmPackageTarget.alias(): RpmPackageTarget,
    }
  )


def register_goals():
  task(name='fetch-remote-files', action=RemoteRpmSourceTask).install('fetch-remote')
  task(name='rpmbuild', action=RpmbuildTask).install('rpmbuild')
