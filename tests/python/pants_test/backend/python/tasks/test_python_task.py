# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.python.tasks.python_task import PythonTask
from pants.util.contextutil import temporary_file_path
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonTaskTest(PythonTaskTestBase):
  class NoopPythonTask(PythonTask):
    def execute(self):
      pass

  @classmethod
  def task_type(cls):
    return cls.NoopPythonTask

  def setUp(self):
    super(PythonTaskTest, self).setUp()

    self.requests = self.create_python_requirement_library('3rdparty/python/requests', 'requests',
                                                           requirements=['requests==2.6.0'])
    self.six = self.create_python_requirement_library('3rdparty/python/six', 'six',
                                                      requirements=['six==1.9.0'])

    self.library = self.create_python_library('src/python/lib', 'lib', {'lib.py': dedent("""
    import six


    def go():
      six.print_('go', 'go', 'go!', sep='')
    """)}, dependencies=['//3rdparty/python/six'])

    self.binary = self.create_python_binary('src/python/bin', 'bin', 'lib.lib:go',
                                            dependencies=['//src/python/lib'])

  def rebind_targets(self):
    # Creates new Target objects to ensure any cached fingerprints are reset and ready to be
    # re-calculated.
    self.reset_build_graph()
    self.requests = self.target('3rdparty/python/requests')
    self.six = self.target('3rdparty/python/six')
    self.library = self.target('src/python/lib')
    self.binary = self.target('src/python/bin')

  @contextmanager
  def cached_chroot(self):
    python_task = self.create_task(self.context(target_roots=[self.binary]))

    interpreter = python_task.select_interpreter_for_targets(self.binary.closure())
    pex_info = self.binary.pexinfo
    platforms = self.binary.platforms

    chroot = python_task.cached_chroot(interpreter, pex_info, [self.binary], platforms)
    with temporary_file_path() as pex:
      chroot.dump()
      chroot.package_pex(pex)
      yield chroot, pex

  def test_cached_chroot_reuse(self):
    with self.cached_chroot() as (chroot1, pex1):
      self.rebind_targets()
      with self.cached_chroot() as (chroot2, pex2):
        self.assertEqual(chroot1.path(), chroot2.path())
        self.assertEqual(subprocess.check_output(pex1), subprocess.check_output(pex2))

  # TODO(John Sirois): Test direct python_binary.source modification after moving
  # PythonTaskTestBase to self.make_target
  def test_cached_chroot_direct_dep_invalidation(self):
    with self.cached_chroot() as (chroot1, pex1):
      self.rebind_targets()
      self.binary.inject_dependency(self.requests.address)
      with self.cached_chroot() as (chroot2, pex2):
        self.assertNotEqual(chroot1.path(), chroot2.path())
        # Adding an unused requests dep does not change the behavior of the binary despite
        # invalidating the chroot
        self.assertEqual(subprocess.check_output(pex1), subprocess.check_output(pex2))

  def test_cached_chroot_transitive_source_invalidation(self):
    with self.cached_chroot() as (chroot1, pex1):
      self.rebind_targets()
      self.create_file('src/python/lib/lib.py', mode='ab',
                       contents="  six.print_('Mad River Glen!')")
      with self.cached_chroot() as (chroot2, pex2):
        self.assertNotEqual(chroot1.path(), chroot2.path())
        self.assertNotEqual(subprocess.check_output(pex1), subprocess.check_output(pex2))

  def test_cached_chroot_transitive_dep_invalidation(self):
    with self.cached_chroot() as (chroot1, pex1):
      self.rebind_targets()
      self.library.inject_dependency(self.requests.address)
      with self.cached_chroot() as (chroot2, pex2):
        self.assertNotEqual(chroot1.path(), chroot2.path())
        # Adding an unused requests dep does not change the behavior of the binary despite
        # invalidating the chroot
        self.assertEqual(subprocess.check_output(pex1), subprocess.check_output(pex2))
