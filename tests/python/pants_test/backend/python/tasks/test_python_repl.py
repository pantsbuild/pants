# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.build_file_layout.source_root import SourceRoot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks.python_repl import PythonRepl
from pants.base.address import SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.util.contextutil import temporary_dir
from pants_test.backend.python.tasks.python_task_test import PythonTaskTest


class PythonReplTest(PythonTaskTest):
  @classmethod
  def task_type(cls):
    return PythonRepl

  class JvmTarget(Target):
    def __init__(self, *args, **kwargs):
      super(PythonReplTest.JvmTarget, self).__init__(*args, **kwargs)
      self.add_labels('jvm')

  @property
  def alias_groups(self):
    return super(PythonReplTest, self).alias_groups.merge(
        BuildFileAliases.create(targets={'jvm_target': self.JvmTarget}))

  def create_non_python_target(self, relpath, name):
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    jvm_target(
      name='{name}',
    )
    """).format(name=name))

    return self.target(SyntheticAddress(relpath, name).spec)

  def setUp(self):
    super(PythonReplTest, self).setUp()

    SourceRoot.register('3rdparty', PythonRequirementLibrary)
    SourceRoot.register('src', PythonBinary, PythonLibrary)

    self.six = self.create_python_requirement_library('3rdparty/six', 'six',
                                                      requirements=['six==1.9.0'])
    self.requests = self.create_python_requirement_library('3rdparty/requests', 'requests',
                                                           requirements=['requests==2.6.0'])

    self.library = self.create_python_library('src/lib', 'lib', {'lib.py': dedent("""
    import six


    def go():
      six.print_('go', 'go', 'go!', sep='')
    """)}, dependencies=['//3rdparty/six'])

    self.binary = self.create_python_binary('src/bin', 'bin', 'lib.go', dependencies=['//src/lib'])

    self.non_python_target = self.create_non_python_target('src/java', 'java')

  def tearDown(self):
    super(PythonReplTest, self).tearDown()
    SourceRoot.reset()

  @contextmanager
  def new_io(self, input):
    orig_stdin, orig_stdout, orig_stderr = sys.stdin, sys.stdout, sys.stderr
    with temporary_dir() as iodir:
      stdin = os.path.join(iodir, 'stdin')
      stdout = os.path.join(iodir, 'stdout')
      stderr = os.path.join(iodir, 'stderr')
      with open(stdin, 'w') as fp:
        fp.write(input)
      with open(stdin, 'rb') as inp, open(stdout, 'wb') as out, open(stderr, 'wb') as err:
        sys.stdin, sys.stdout, sys.stderr = inp, out, err
        try:
          yield inp, out, err
        finally:
          sys.stdin, sys.stdout, sys.stderr = orig_stdin, orig_stdout, orig_stderr

  def do_test_repl(self, code, expected, targets, options=None):
    if options:
      self.set_options(**options)
    python_repl = self.create_task(self.context(target_roots=targets))

    with self.new_io('\n'.join(code)) as (inp, out, err):
      python_repl.execute(stdin=inp, stdout=out, stderr=err)
      with open(out.name) as fp:
        lines = fp.read()
        if not expected:
          self.assertEqual('', lines)
        else:
          for expectation in expected:
            self.assertIn(expectation, lines)

  def do_test_library(self, *targets):
    self.do_test_repl(code=['from lib.lib import go',
                            'go()'],
                      expected=['gogogo!'],
                      targets=targets)

  def test_library(self):
    self.do_test_library(self.library)

  def test_binary(self):
    self.do_test_library(self.binary)

  def test_requirement(self):
    self.do_test_repl(code=['import six',
                            'print("python 2?:{}".format(six.PY2))'],
                      expected=['python 2?:True'],
                      targets=[self.six])

  def test_mixed_python(self):
    self.do_test_repl(code=['import requests',
                            'import six',
                            'from lib.lib import go',
                            'print("teapot response code is: {}".format(requests.codes.teapot))',
                            'go()',
                            'print("python 2?:{}".format(six.PY2))'],
                      expected=['teapot response code is: 418',
                                'gogogo!',
                                'python 2?:True'],
                      targets=[self.requests, self.binary])

  def test_disallowed_mix(self):
    with self.assertRaises(TaskError):
      self.do_test_repl(code=['print("unreachable")'],
                        expected=[],
                        targets=[self.library, self.non_python_target])

  def test_non_python_targets(self):
    self.do_test_repl(code=['import java.lang.unreachable'],
                      expected=[''],
                      targets=[self.non_python_target])

  def test_ipython(self):
    # IPython supports shelling out with a leading !, so indirectly test its presence by reading
    # the head of this very file.
    with open(__file__) as fp:
      me = fp.readline()
      self.do_test_repl(code=['!head -1 {}'.format(__file__)],
                        expected=[me],
                        targets=[self.six],  # Just to get the repl to pop up.
                        options={'ipython': True})
