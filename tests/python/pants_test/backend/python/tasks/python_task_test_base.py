# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.python.register import build_file_aliases as register_python
from pants.build_graph.address import Address
from pants_test.backend.python.tasks.interpreter_cache_test_mixin import InterpreterCacheTestMixin
from pants_test.tasks.task_test_base import TaskTestBase


class PythonTaskTestBase(InterpreterCacheTestMixin, TaskTestBase):
  """
  :API: public
  """

  @property
  def alias_groups(self):
    """
    :API: public
    """
    return register_python()

  def create_python_library(self, relpath, name, source_contents_map=None,
                            dependencies=(), provides=None):
    """
    :API: public
    """
    sources = ['__init__.py'] + source_contents_map.keys() if source_contents_map else None
    sources_strs = ["'{0}'".format(s) for s in sources] if sources else None
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
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

  def create_python_binary(self, relpath, name, entry_point, dependencies=(), provides=None):
    """
    :API: public
    """
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    python_binary(
      name='{name}',
      entry_point='{entry_point}',
      dependencies=[
        {dependencies}
      ],
      {provides_clause}
    )
    """).format(name=name, entry_point=entry_point, dependencies=','.join(map(repr, dependencies)),
                provides_clause='provides={0},'.format(provides) if provides else ''))
    return self.target(Address(relpath, name).spec)

  def create_python_requirement_library(self, relpath, name, requirements):
    """
    :API: public
    """
    def make_requirement(req):
      return 'python_requirement("{}")'.format(req)

    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    python_requirement_library(
      name='{name}',
      requirements=[
        {requirements}
      ]
    )
    """).format(name=name, requirements=','.join(map(make_requirement, requirements))))
    return self.target(Address(relpath, name).spec)
