# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mock
from pex.interpreter import PythonIdentity, PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter
from pants.base.exceptions import TaskError
from pants_test.tasks.task_test_base import TaskTestBase


class SelectInterpreterTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return SelectInterpreter

  def setUp(self):
    super(SelectInterpreterTest, self).setUp()

    self.set_options(interpreter=['FakePython>=2.55'])
    self.set_options_for_scope(PythonSetup.options_scope)

    def fake_interpreter(id_str):
      return PythonInterpreter('/fake/binary', PythonIdentity.from_id_string(id_str))

    self.fake_interpreters = [
      fake_interpreter('FakePython 2 77 777'),
      fake_interpreter('FakePython 2 88 888'),
      fake_interpreter('FakePython 2 99 999')
    ]

    self.tgt1 = self._fake_target('tgt1')
    self.tgt2 = self._fake_target('tgt2', compatibility=['FakePython>2.77.777'])
    self.tgt3 = self._fake_target('tgt3', compatibility=['FakePython>2.88.888'])
    self.tgt4 = self._fake_target('tgt4', compatibility=['FakePython<2.99.999'])
    self.tgt20 = self._fake_target('tgt20', dependencies=[self.tgt2])
    self.tgt30 = self._fake_target('tgt30', dependencies=[self.tgt3])
    self.tgt40 = self._fake_target('tgt40', dependencies=[self.tgt4])

  def _fake_target(self, spec, compatibility=None, sources=None, dependencies=None):
    return self.make_target(spec=spec, target_type=PythonLibrary, sources=sources or [],
                            dependencies=dependencies, compatibility=compatibility)

  def _select_interpreter(self, target_roots, should_invalidate=None):
    """Return the version string of the interpreter selected for the target roots."""
    context = self.context(target_roots=target_roots)
    task = self.create_task(context)
    if should_invalidate is not None:
      task._create_interpreter_path_file = mock.MagicMock(wraps=task._create_interpreter_path_file)

    # Mock out the interpreter cache setup, so we don't actually look for real interpreters
    # on the filesystem.
    with mock.patch.object(PythonInterpreterCache, 'setup', autospec=True) as mock_resolve:
      def se(me, *args, **kwargs):
        me._interpreters = self.fake_interpreters
        return self.fake_interpreters
      mock_resolve.side_effect = se
      task.execute()

    if should_invalidate is not None:
      if should_invalidate:
        task._create_interpreter_path_file.assert_called_once()
      else:
        task._create_interpreter_path_file.assert_not_called()

    interpreter = context.products.get_data(PythonInterpreter)
    self.assertTrue(isinstance(interpreter, PythonInterpreter))
    return interpreter.version_string

  def test_interpreter_selection(self):
    self.assertEquals('FakePython-2.77.777', self._select_interpreter([]))
    self.assertEquals('FakePython-2.77.777', self._select_interpreter([self.tgt1]))
    self.assertEquals('FakePython-2.88.888', self._select_interpreter([self.tgt2]))
    self.assertEquals('FakePython-2.99.999', self._select_interpreter([self.tgt3]))
    self.assertEquals('FakePython-2.77.777', self._select_interpreter([self.tgt4]))
    self.assertEquals('FakePython-2.88.888', self._select_interpreter([self.tgt20]))
    self.assertEquals('FakePython-2.99.999', self._select_interpreter([self.tgt30]))
    self.assertEquals('FakePython-2.77.777', self._select_interpreter([self.tgt40]))
    self.assertEquals('FakePython-2.99.999', self._select_interpreter([self.tgt2, self.tgt3]))
    self.assertEquals('FakePython-2.88.888', self._select_interpreter([self.tgt2, self.tgt4]))

    with self.assertRaises(TaskError) as cm:
      self._select_interpreter([self.tgt3, self.tgt4])
    self.assertIn('Unable to detect a suitable interpreter for compatibilities: '
                  'FakePython<2.99.999 && FakePython>2.88.888', str(cm.exception))

  def test_interpreter_selection_invalidation(self):
    tgta = self._fake_target('tgta', compatibility=['FakePython>2.77.777'],
                             dependencies=[self.tgt3])
    self.assertEquals('FakePython-2.99.999',
                      self._select_interpreter([tgta], should_invalidate=True))

    # A new target with different sources, but identical compatibility, shouldn't invalidate.
    self.create_file('tgtb/foo/bar/baz.py', 'fake content')
    tgtb = self._fake_target('tgtb', compatibility=['FakePython>2.77.777'],
                             dependencies=[self.tgt3], sources=['foo/bar/baz.py'])
    self.assertEquals('FakePython-2.99.999',
                      self._select_interpreter([tgtb], should_invalidate=False))
