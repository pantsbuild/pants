# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.build_graph.files import Files
from pants.build_graph.resources import Resources
from pants.python.python_repos import PythonRepos
from pants.source.source_root import SourceRootConfig
from pants_test.tasks.task_test_base import TaskTestBase


class GatherSourcesTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return GatherSources

  def setUp(self):
    super(GatherSourcesTest, self).setUp()

    self.filemap = {
      'src/python/one/foo.py': 'foo_py_content',
      'src/python/one/bar.py': 'bar_py_content',
      'src/python/two/baz.py': 'baz_py_content',
      'resources/qux/quux.txt': 'quux_txt_content',
    }
    # Pants does not do auto-detection of Resources target roots unless they are nested under some
    # other source root so we erect a manual resources root here.
    self.set_options_for_scope(SourceRootConfig.options_scope, source_roots={'resources': ()})

    for rel_path, content in self.filemap.items():
      self.create_file(rel_path, content)

    self.sources1 = self.make_target(spec='src/python/one:sources1_tgt', target_type=PythonLibrary,
                                     sources=['foo.py', 'bar.py'])
    self.sources2 = self.make_target(spec='src/python/two:sources2_tgt', target_type=PythonLibrary,
                                     sources=['baz.py'])
    self.resources = self.make_target(spec='resources/qux:resources_tgt', target_type=Resources,
                                      sources=['quux.txt'])
    self.files = self.make_target(spec='resources/qux:files_tgt', target_type=Files,
                                  sources=['quux.txt'])

  def _assert_content(self, pex, relpath, prefix=None):
    expected_content = self.filemap[os.path.join(prefix, relpath) if prefix else relpath]
    with open(os.path.join(pex.path(), relpath)) as infile:
      content = infile.read()
    self.assertEquals(expected_content, content)

  def test_gather_sources(self):
    pex = self._gather_sources([self.sources1, self.sources2, self.resources])
    self._assert_content(pex, 'one/foo.py', prefix='src/python')
    self._assert_content(pex, 'one/bar.py', prefix='src/python')
    self._assert_content(pex, 'two/baz.py', prefix='src/python')
    self._assert_content(pex, 'qux/quux.txt', prefix='resources')

  def test_gather_files(self):
    pex = self._gather_sources([self.sources2, self.files])
    self._assert_content(pex, 'two/baz.py', prefix='src/python')
    self._assert_content(pex, 'resources/qux/quux.txt')

  def _gather_sources(self, target_roots):
    context = self.context(target_roots=target_roots, for_subsystems=[PythonSetup, PythonRepos])

    # We must get an interpreter via the cache, instead of using PythonInterpreter.get() directly,
    # to ensure that the interpreter has setuptools and wheel support.
    interpreter = PythonInterpreter.get()
    interpreter_cache = PythonInterpreterCache(PythonSetup.global_instance(),
                                               PythonRepos.global_instance(),
                                               logger=context.log.debug)
    interpreters = interpreter_cache.setup(paths=[os.path.dirname(interpreter.binary)],
                                           filters=[str(interpreter.identity.requirement)])
    context.products.get_data(PythonInterpreter, lambda: interpreters[0])

    task = self.create_task(context)
    task.execute()

    return context.products.get_data(GatherSources.PYTHON_SOURCES)
