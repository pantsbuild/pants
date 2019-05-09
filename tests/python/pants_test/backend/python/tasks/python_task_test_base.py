# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import map
from textwrap import dedent

from pex import pep425tags

from pants.backend.python.register import build_file_aliases as register_python
from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.address import Address
from pants_test.backend.python.tasks.interpreter_cache_test_mixin import InterpreterCacheTestMixin
from pants_test.subsystem import subsystem_util
from pants_test.task_test_base import TaskTestBase


def normalize_platform_tag(platform_tag):
  return platform_tag.replace('-', '_')


def name_and_platform(whl):
  # The wheel filename is of the format
  # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
  # See https://www.python.org/dev/peps/pep-0425/.
  # We don't care about the python or abi versions (they depend on what we're currently
  # running on), we just want to make sure we have all the platforms we expect.
  parts = os.path.splitext(whl)[0].split('-')
  dist = parts[0]
  version = parts[1]
  platform_tag = parts[-1]
  return dist, version, normalize_platform_tag(platform_tag)


def normalized_current_platform():
  return normalize_platform_tag(pep425tags.get_platform())


class PythonTaskTestBase(InterpreterCacheTestMixin, TaskTestBase):
  """
  :API: public
  """

  @classmethod
  def alias_groups(cls):
    """
    :API: public
    """
    return register_python()

  def setUp(self):
    super(PythonTaskTestBase, self).setUp()
    subsystem_util.init_subsystem(PythonBinary.Defaults)

  def create_python_library(self, relpath, name, source_contents_map=None,
                            dependencies=(), provides=None):
    """
    :API: public
    """
    sources = None if source_contents_map is None else ['__init__.py'] + list(source_contents_map.keys())
    sources_strs = ["'{0}'".format(s) for s in sources] if sources else None
    self.add_to_build_file(relpath=relpath, target=dedent("""
    python_library(
      name='{name}',
      {sources_clause}
      dependencies=[
        {dependencies}
      ],
      {provides_clause}
    )
    """).format(
      name=name,
      sources_clause='sources=[{0}],'.format(','.join(sources_strs)) if sources_strs else '',
      dependencies=','.join(map(repr, dependencies)),
      provides_clause='provides={0},'.format(provides) if provides else ''))
    if source_contents_map:
      self.create_file(relpath=os.path.join(relpath, '__init__.py'))
      for source, contents in source_contents_map.items():
        self.create_file(relpath=os.path.join(relpath, source), contents=contents)
    return self.target(Address(relpath, name).spec)

  def create_python_binary(self, relpath, name, entry_point, dependencies=(), provides=None, shebang=None):
    """
    :API: public
    """
    self.add_to_build_file(relpath=relpath, target=dedent("""
    python_binary(
      name='{name}',
      entry_point='{entry_point}',
      dependencies=[
        {dependencies}
      ],
      {provides_clause}
      {shebang_clause}
    )
    """).format(name=name, entry_point=entry_point, dependencies=','.join(map(repr, dependencies)),
                provides_clause='provides={0},'.format(provides) if provides else '',
                shebang_clause='shebang={!r},'.format(shebang) if shebang else ''))
    return self.target(Address(relpath, name).spec)

  def create_python_requirement_library(self, relpath, name, requirements):
    """
    :API: public
    """
    def make_requirement(req):
      return 'python_requirement("{}")'.format(req)

    self.add_to_build_file(relpath=relpath, target=dedent("""
    python_requirement_library(
      name='{name}',
      requirements=[
        {requirements}
      ]
    )
    """).format(name=name, requirements=','.join(map(make_requirement, requirements))))
    return self.target(Address(relpath, name).spec)
