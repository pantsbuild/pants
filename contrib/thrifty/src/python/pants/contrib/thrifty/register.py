# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.thrifty.java_thrifty_gen import JavaThriftyGen
from pants.contrib.thrifty.java_thrifty_library import JavaThriftyLibrary


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'java_thrifty_library': JavaThriftyLibrary,
    }
  )


def register_goals():
  task(name='thrifty', action=JavaThriftyGen).install('gen')
