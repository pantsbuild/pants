# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.gather_sources import GatherSources
from pants.build_graph.files import Files
from pants.build_graph.resources import Resources
from pants.python.python_setup import PythonSetup
from pants.source.source_root import SourceRootConfig
from pants.testutil.task_test_base import TaskTestBase
from pants.util.contextutil import temporary_dir


class GatherSourcesTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return GatherSources

    def setUp(self):
        super().setUp()

        self.filemap = {
            "src/python/one/foo.py": "foo_py_content",
            "src/python/one/bar.py": "bar_py_content",
            "src/python/two/baz.py": "baz_py_content",
            "resources/qux/quux.txt": "quux_txt_content",
            "more/src/python/three/corge.py": "corge_py_content",
        }
        # Pants does not do auto-detection of Resources target roots unless they are nested under some
        # other source root so we erect a manual resources root here.
        self.set_options_for_scope(SourceRootConfig.options_scope, source_roots={"resources": ()})

        for rel_path, content in self.filemap.items():
            self.create_file(rel_path, content)

        self.resources = self.make_target(
            spec="resources/qux:resources_tgt", target_type=Resources, sources=["quux.txt"]
        )
        self.files = self.make_target(
            spec="resources/qux:files_tgt", target_type=Files, sources=["quux.txt"]
        )
        self.sources1 = self.make_target(
            spec="src/python/one:sources1_tgt",
            target_type=PythonLibrary,
            sources=["foo.py", "bar.py"],
            dependencies=[self.resources],
        )
        self.sources2 = self.make_target(
            spec="src/python/two:sources2_tgt",
            target_type=PythonLibrary,
            sources=["baz.py"],
            dependencies=[self.files],
        )
        self.sources3 = self.make_target(
            spec="more/src/python/three:sources3_tgt",
            target_type=PythonLibrary,
            sources=["corge.py"],
            dependencies=[self.files, self.resources],
        )

    def _extract_files(self, target):
        if type(target) == Files:
            to_filemap_key = lambda path: path
            files = target.sources_relative_to_buildroot()
        else:
            to_filemap_key = lambda path: os.path.join(target.target_base, path)
            files = target.sources_relative_to_source_root()
        return to_filemap_key, files

    def _assert_content_in_pex(self, pex, target):
        to_filemap_key, files = self._extract_files(target)
        pex_path = pex.path()
        for path in files:
            expected_content = self.filemap[to_filemap_key(path)]
            with open(os.path.join(pex_path, path), "r") as infile:
                content = infile.read()
            self.assertEqual(expected_content, content)

    def _assert_content_not_in_pex(self, pex, target):
        _, files = self._extract_files(target)
        pex_path = pex.path()
        for path in files:
            self.assertFalse(os.path.exists(os.path.join(pex_path, path)))

    def test_gather_sources(self):
        pex = self._gather_sources(
            [
                self.sources1,
                # These files should not be gathered since they are not
                # a dependency of any python targets in play.
                self.files,
            ]
        )
        self._assert_content_in_pex(pex, self.sources1)
        self._assert_content_in_pex(pex, self.resources)
        self._assert_content_not_in_pex(pex, self.sources2)
        self._assert_content_not_in_pex(pex, self.files)

    def test_gather_files(self):
        pex = self._gather_sources(
            [
                self.sources2,
                # These resources should not be gathered since they are
                # not a dependency of any python targets in play.
                self.resources,
            ]
        )
        self._assert_content_in_pex(pex, self.sources2)
        self._assert_content_in_pex(pex, self.files)
        self._assert_content_not_in_pex(pex, self.sources1)
        self._assert_content_not_in_pex(pex, self.resources)

    def _gather_sources(self, target_roots):
        with temporary_dir() as cache_dir:
            interpreter = PythonInterpreter.get()
            context = self.context(
                target_roots=target_roots,
                for_subsystems=[PythonInterpreterCache],
                options={
                    PythonSetup.options_scope: {
                        "interpreter_cache_dir": cache_dir,
                        "interpreter_search_paths": [os.path.dirname(interpreter.binary)],
                    }
                },
            )

            # We must get an interpreter via the cache, instead of using the value of
            # PythonInterpreter.get() directly, to ensure that the interpreter has setuptools and
            # wheel support.
            interpreter_cache = PythonInterpreterCache.global_instance()
            interpreters = interpreter_cache.setup(filters=[str(interpreter.identity.requirement)])
            context.products.get_data(PythonInterpreter, lambda: interpreters[0])

            task = self.create_task(context)
            task.execute()

            return context.products.get_data(GatherSources.PYTHON_SOURCES)
