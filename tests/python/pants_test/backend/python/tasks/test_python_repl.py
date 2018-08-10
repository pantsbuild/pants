# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import open
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.python_repl import PythonRepl
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.task.repl_task_mixin import ReplTaskMixin
from pants.util.contextutil import environment_as, stdio_as, temporary_dir
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonReplTest(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PythonRepl

  class JvmTarget(Target):
    pass

  @classmethod
  def alias_groups(cls):
    return super(PythonReplTest, cls).alias_groups().merge(
        BuildFileAliases(targets={'jvm_target': cls.JvmTarget}))

  def create_non_python_target(self, relpath, name):
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    jvm_target(
      name='{name}',
    )
    """).format(name=name))

    return self.target(Address(relpath, name).spec)

  def setUp(self):
    super(PythonReplTest, self).setUp()
    self.six = self.create_python_requirement_library('3rdparty/python/six', 'six',
                                                      requirements=['six==1.9.0'])
    self.requests = self.create_python_requirement_library('3rdparty/python/requests', 'requests',
                                                           requirements=['requests==2.6.0'])

    self.library = self.create_python_library('src/python/lib', 'lib', {'lib.py': dedent("""
    import six


    def go():
      six.print_('go', 'go', 'go!', sep='')
    """)}, dependencies=['//3rdparty/python/six'])

    self.binary = self.create_python_binary('src/python/bin', 'bin', 'lib.go',
                                            dependencies=['//src/python/lib'])

    self.non_python_target = self.create_non_python_target('src/python/java', 'java')

  def tearDown(self):
    super(PythonReplTest, self).tearDown()
    ReplTaskMixin.reset_implementations()

  @contextmanager
  def new_io(self, stdin_data):
    with temporary_dir() as iodir:
      stdin = os.path.join(iodir, 'stdin')
      stdout = os.path.join(iodir, 'stdout')
      stderr = os.path.join(iodir, 'stderr')
      with open(stdin, 'w') as fp:
        fp.write(stdin_data)
      with open(stdin, 'r') as inp, open(stdout, 'w') as out, open(stderr, 'w') as err:
        with stdio_as(stdin_fd=inp.fileno(), stdout_fd=out.fileno(), stderr_fd=err.fileno()):
          yield (stdin, stdout, stderr)

  def do_test_repl(self, code, expected, targets, options=None):
    if options:
      self.set_options(**options)

    class JvmRepl(ReplTaskMixin):
      options_scope = 'test_scope_jvm_repl'

      @classmethod
      def select_targets(cls, target):
        return isinstance(target, self.JvmTarget)

      def setup_repl_session(_, targets):
        raise AssertionError()

      def launch_repl(_, session_setup):
        raise AssertionError()

    # Add a competing REPL impl.
    JvmRepl.prepare(self.options, round_manager=None)

    # The easiest way to create products required by the PythonRepl task is to
    # execute the relevant tasks.
    si_task_type = self.synthesize_task_subtype(SelectInterpreter, 'si_scope')
    rr_task_type = self.synthesize_task_subtype(ResolveRequirements, 'rr_scope')
    gs_task_type = self.synthesize_task_subtype(GatherSources, 'gs_scope')
    context = self.context(for_task_types=[si_task_type, rr_task_type, gs_task_type],
                           target_roots=targets)
    si_task_type(context, os.path.join(self.pants_workdir, 'si')).execute()
    rr_task_type(context, os.path.join(self.pants_workdir, 'rr')).execute()
    gs_task_type(context, os.path.join(self.pants_workdir, 'gs')).execute()
    python_repl = self.create_task(context)

    with self.new_io('\n'.join(code)) as (inp, out, err):
      python_repl.execute()
      with open(out, 'r') as fp:
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

  def test_access_to_env(self):
    with environment_as(SOME_ENV_VAR='twelve'):
      self.do_test_repl(code=['import os',
                               'print(os.environ.get("SOME_ENV_VAR"))'],
                        expected=['twelve'],
                        targets=[self.library])

  def test_ipython(self):
    # IPython supports shelling out with a leading !, so indirectly test its presence by reading
    # the head of this very file.
    with open(__file__, 'r') as fp:
      me = fp.readline()
      self.do_test_repl(code=['!head -1 {}'.format(__file__)],
                        expected=[me],
                        targets=[self.six],  # Just to get the repl to pop up.
                        options={'ipython': True})
