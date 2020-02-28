# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import subprocess

from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.base.build_environment import get_buildroot
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup
from pants.testutil.task_test_base import TaskTestBase
from pants.util.contextutil import temporary_dir, temporary_file


class ResolveRequirementsTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return ResolveRequirements

    def test_resolve_simple_requirements(self):
        noreqs_tgt = self._fake_target("noreqs", [])
        ansicolors_tgt = self._fake_target("ansicolors", ["ansicolors==1.0.2"])

        # Check that the module is unavailable unless specified as a requirement (proves that
        # the requirement isn't sneaking in some other way, which would render the remainder
        # of this test moot.)
        _, stderr_data = self._exercise_module(self._resolve_requirements([noreqs_tgt]), "colors")

        try:
            self.assertIn("ModuleNotFoundError: No module named 'colors'", stderr_data)
        except AssertionError:
            # < Python 3.6 uses ImportError instead of ModuleNotFoundError.
            # Python < 3 uses not quotes for module, python >= 3 does.
            self.assertNotEqual(
                re.search(r"ImportError: No module named '?colors'?", stderr_data), None
            )

        # Check that the module is available if specified as a requirement.
        stdout_data, stderr_data = self._exercise_module(
            self._resolve_requirements([ansicolors_tgt]), "colors"
        )
        self.assertEqual("", stderr_data.strip())

        path = stdout_data.strip()
        # Check that the requirement resolved to what we expect.
        self.assertTrue(path.endswith("/.deps/ansicolors-1.0.2-py3-none-any.whl/colors.py"))
        # Check that the path is under the test's build root, so we know the pex was created there.
        self.assertTrue(path.startswith(os.path.realpath(get_buildroot())))

    def _fake_target(self, spec, requirement_strs):
        requirements = [PythonRequirement(r) for r in requirement_strs]
        return self.make_target(
            spec=spec, target_type=PythonRequirementLibrary, requirements=requirements
        )

    def _resolve_requirements(self, target_roots, options=None):
        with temporary_dir() as cache_dir:
            options = options or {}
            python_setup_opts = options.setdefault(PythonSetup.options_scope, {})
            python_setup_opts["interpreter_cache_dir"] = cache_dir
            interpreter = PythonInterpreter.get()
            python_setup_opts["interpreter_search_paths"] = [os.path.dirname(interpreter.binary)]
            context = self.context(
                target_roots=target_roots, options=options, for_subsystems=[PythonInterpreterCache]
            )

            # We must get an interpreter via the cache, instead of using the value of
            # PythonInterpreter.get() directly, to ensure that the interpreter has setuptools and
            # wheel support.
            interpreter_cache = PythonInterpreterCache.global_instance()
            interpreters = interpreter_cache.setup(filters=[str(interpreter.identity.requirement)])
            context.products.get_data(PythonInterpreter, lambda: interpreters[0])

            task = self.create_task(context)
            task.execute()

            return context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX)

    def _exercise_module(self, pex, expected_module):
        with temporary_file(binary_mode=False) as f:
            f.write("import {m}; print({m}.__file__)".format(m=expected_module))
            f.close()
            proc = pex.run(
                args=[f.name], blocking=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = proc.communicate()
            return (stdout.decode(), stderr.decode())
