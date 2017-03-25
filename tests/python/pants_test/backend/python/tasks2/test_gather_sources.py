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
from pants.build_graph.resources import Resources
from pants.python.python_repos import PythonRepos
from pants_test.tasks.task_test_base import TaskTestBase


class GatherSourcesTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return GatherSources

  def test_gather_sources(self):
    filemap = {
      'src/python/foo.py': 'foo_py_content',
      'src/python/bar.py': 'bar_py_content',
      'src/python/baz.py': 'baz_py_content',
      'resources/qux/quux.txt': 'quux_txt_content',
    }

    for rel_path, content in filemap.items():
      self.create_file(rel_path, content)

    sources1 = self.make_target(spec='//:sources1_tgt', target_type=PythonLibrary,
                                sources=['src/python/foo.py', 'src/python/bar.py'])
    sources2 = self.make_target(spec='//:sources2_tgt', target_type=PythonLibrary,
                                sources=['src/python/baz.py'])
    resources = self.make_target(spec='//:resources_tgt', target_type=Resources,
                                 sources=['resources/qux/quux.txt'])
    pex = self._gather_sources([sources1, sources2, resources])
    pex_root = pex.cmdline()[1]

    for rel_path, expected_content in filemap.items():
      with open(os.path.join(pex_root, rel_path)) as infile:
        content = infile.read()
      self.assertEquals(expected_content, content)

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
