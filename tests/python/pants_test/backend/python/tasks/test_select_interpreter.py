# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import unittest.mock
from textwrap import dedent
from typing import Tuple

from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.base.exceptions import TaskError
from pants.option.ranked_value import Rank, RankedValue
from pants.python.python_setup import PythonSetup
from pants.testutil.task_test_base import TaskTestBase
from pants.util.dirutil import chmod_plus_x, safe_mkdtemp


class SelectInterpreterTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return SelectInterpreter

    def setUp(self):
        super().setUp()

        # We're tied tightly to pex implementation details here faking out a python binary that outputs
        # only one value no matter what arguments, environment or input stream it has attached. That
        # value is the interpreter identity which is a JSON dict with exactly the following keys:
        # binary, python_tag, abi_tag, platform_tag, version, supported_tags, env_markers.
        def fake_interpreter(python_tag: str, abi_tag: str, version: Tuple[int, int, int]):
            interpreter_dir = safe_mkdtemp()
            binary = os.path.join(interpreter_dir, "python")
            values = dict(
                binary=binary,
                python_tag=python_tag,
                abi_tag=abi_tag,
                platform_tag="",
                version=version,
                supported_tags=[],
                env_markers={},
            )
            id_str = json.dumps(values)
            with open(binary, "w") as fp:
                fp.write(
                    dedent(
                        f"""
                        #!{PythonInterpreter.get().binary}
                        from __future__ import print_function

                        print({id_str!r})
                        """
                    ).strip()
                )
            chmod_plus_x(binary)
            return PythonInterpreter.from_binary(binary)

        # impl, abi, impl_version, major, minor, patch
        self.fake_interpreters = [
            fake_interpreter(python_tag="ip", abi_tag="ip2", version=(2, 77, 777)),
            fake_interpreter(python_tag="ip", abi_tag="ip2", version=(2, 88, 888)),
            fake_interpreter(python_tag="ip", abi_tag="ip2", version=(2, 99, 999)),
        ]

        self.set_options_for_scope(
            PythonSetup.options_scope,
            interpreter_constraints=RankedValue(Rank.CONFIG, ["IronPython>=2.55"]),
            interpreter_search_paths=[interpreter.binary for interpreter in self.fake_interpreters],
        )

        self.reqtgt = self.make_target(
            spec="req", target_type=PythonRequirementLibrary, requirements=[],
        )
        self.tgt1 = self._fake_target("tgt1")
        self.tgt2 = self._fake_target("tgt2", compatibility=["IronPython>2.77.777"])
        self.tgt3 = self._fake_target("tgt3", compatibility=["IronPython>2.88.888"])
        self.tgt4 = self._fake_target("tgt4", compatibility=["IronPython<2.99.999"])
        self.tgt20 = self._fake_target("tgt20", dependencies=[self.tgt2])
        self.tgt30 = self._fake_target("tgt30", dependencies=[self.tgt3])
        self.tgt40 = self._fake_target("tgt40", dependencies=[self.tgt4])

    def _fake_target(self, spec, compatibility=None, sources=None, dependencies=None):
        return self.make_target(
            spec=spec,
            target_type=PythonLibrary,
            sources=sources or [],
            dependencies=dependencies,
            compatibility=compatibility,
        )

    def _select_interpreter(self, target_roots, should_invalidate=None):
        context = self.context(target_roots=target_roots)

        task = self.create_task(context)
        if should_invalidate is not None:
            task._select_interpreter = unittest.mock.MagicMock(wraps=task._select_interpreter)

        task.execute()

        if should_invalidate is not None:
            if should_invalidate:
                task._select_interpreter.assert_called_once()
            else:
                task._select_interpreter.assert_not_called()

        return context.products.get_data(PythonInterpreter)

    def _select_interpreter_and_get_version(self, target_roots, should_invalidate=None):
        """Return the version string of the interpreter selected for the target roots."""
        interpreter = self._select_interpreter(target_roots, should_invalidate)
        self.assertTrue(isinstance(interpreter, PythonInterpreter))
        return interpreter.version_string

    def test_interpreter_selection(self):
        self.assertIsNone(self._select_interpreter([]))
        self.assertEqual(
            "IronPython-2.77.777", self._select_interpreter_and_get_version([self.reqtgt])
        )
        self.assertEqual(
            "IronPython-2.77.777", self._select_interpreter_and_get_version([self.tgt1])
        )
        self.assertEqual(
            "IronPython-2.88.888", self._select_interpreter_and_get_version([self.tgt2])
        )
        self.assertEqual(
            "IronPython-2.99.999", self._select_interpreter_and_get_version([self.tgt3])
        )
        self.assertEqual(
            "IronPython-2.77.777", self._select_interpreter_and_get_version([self.tgt4])
        )
        self.assertEqual(
            "IronPython-2.88.888", self._select_interpreter_and_get_version([self.tgt20])
        )
        self.assertEqual(
            "IronPython-2.99.999", self._select_interpreter_and_get_version([self.tgt30])
        )
        self.assertEqual(
            "IronPython-2.77.777", self._select_interpreter_and_get_version([self.tgt40])
        )
        self.assertEqual(
            "IronPython-2.99.999", self._select_interpreter_and_get_version([self.tgt2, self.tgt3])
        )
        self.assertEqual(
            "IronPython-2.88.888", self._select_interpreter_and_get_version([self.tgt2, self.tgt4])
        )

        with self.assertRaises(TaskError) as cm:
            self._select_interpreter_and_get_version([self.tgt3, self.tgt4])
        self.assertIn(
            "Unable to detect a suitable interpreter for compatibilities: "
            "IronPython<2.99.999 && IronPython>2.88.888",
            str(cm.exception),
        )

    def test_invalidation_for_target_constraints(self):
        tgta = self._fake_target(
            "tgta", compatibility=["IronPython>2.77.777"], dependencies=[self.tgt3]
        )
        self.assertEqual(
            "IronPython-2.99.999",
            self._select_interpreter_and_get_version([tgta], should_invalidate=True),
        )

        # A new target with different sources, but identical compatibility, shouldn't invalidate.
        self.create_file("tgtb/foo/bar/baz.py", "fake content")
        tgtb = self._fake_target(
            "tgtb",
            compatibility=["IronPython>2.77.777"],
            dependencies=[self.tgt3],
            sources=["foo/bar/baz.py"],
        )
        self.assertEqual(
            "IronPython-2.99.999",
            self._select_interpreter_and_get_version([tgtb], should_invalidate=False),
        )

    def test_invalidation_for_global_constraints(self):
        # Because the system is setup with interpreter constraints, the task should
        # invalidate on the first run.
        self._select_interpreter_and_get_version([self.tgt1], should_invalidate=True)
        self.set_options_for_scope(
            PythonSetup.options_scope,
            interpreter_constraints=RankedValue(Rank.CONFIG, ["IronPython>2.77.777"]),
        )
        # After changing the global interpreter constraints, the task should invalidate.
        self._select_interpreter_and_get_version([self.tgt1], should_invalidate=True)
        # If the global constraints don't change, the task should not invalidate.
        self._select_interpreter_and_get_version([self.tgt1], should_invalidate=False)

    def test_compatibility_AND(self):
        tgt = self._fake_target("tgt5", compatibility=["IronPython>2.77.777,<2.99.999"])
        self.assertEqual("IronPython-2.88.888", self._select_interpreter_and_get_version([tgt]))

    def test_compatibility_AND_impossible(self):
        tgt = self._fake_target("tgt5", compatibility=["IronPython>2.77.777,<2.88.888"])

        with self.assertRaises(PythonInterpreterCache.UnsatisfiableInterpreterConstraintsError):
            self._select_interpreter_and_get_version([tgt])

    def test_compatibility_OR(self):
        tgt = self._fake_target("tgt6", compatibility=["IronPython>2.88.888", "IronPython<2.7"])
        self.assertEqual("IronPython-2.99.999", self._select_interpreter_and_get_version([tgt]))

    def test_compatibility_OR_impossible(self):
        tgt = self._fake_target(
            "tgt6", compatibility=["IronPython>2.99.999", "IronPython<2.77.777"]
        )

        with self.assertRaises(PythonInterpreterCache.UnsatisfiableInterpreterConstraintsError):
            self._select_interpreter_and_get_version([tgt])

    def test_stale_binary_detected(self):
        interpreter1 = self._select_interpreter([self.tgt2])
        os.remove(interpreter1.binary)
        interpreter2 = self._select_interpreter([self.tgt2])
        self.assertNotEqual(interpreter1.binary, interpreter2.binary)
