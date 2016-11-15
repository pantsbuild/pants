# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.python_setup import PythonRepos
from pants.backend.python.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks2.resolve_requirements import ResolveRequirements
from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_file
from pants_test.tasks.task_test_base import TaskTestBase


class ResolveRequirementsTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return ResolveRequirements

  def setUp(self):
    super(ResolveRequirementsTest, self).setUp()

    def fake_target(spec, requirement_strs):
      requirements = [PythonRequirement(r) for r in requirement_strs]
      return self.make_target(spec=spec, target_type=PythonRequirementLibrary,
                              requirements=requirements)

    self.noreqs = fake_target('noreqs', [])
    self.ansicolors = fake_target('ansicolors', ['ansicolors==1.0.2'])

  def _resolve_requirements(self, target_roots):

    context = self.context(target_roots=target_roots)

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

    return context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX)

  def test_resolve_requirements(self):
    module = 'colors'

    def exercise_module(tgt):
      pex = self._resolve_requirements([tgt])
      with temporary_file() as f:
        f.write('import {m}; print({m}.__file__)'.format(m=module))
        f.close()
        proc = pex.run(args=[f.name], blocking=False,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc.communicate()

    # Check that the module is unavailable unless specified as a requirement (proves that
    # the requirement isn't sneaking in some other way, which would render the remainder
    # of this test moot.)
    _, stderr_data = exercise_module(self.noreqs)
    self.assertIn('ImportError: No module named {}'.format(module), stderr_data)

    # Check that the module is available if specified as a requirement.
    stdout_data, stderr_data = exercise_module(self.ansicolors)
    self.assertEquals('', stderr_data.strip())

    path = stdout_data.strip()
    # Check that the requirement resolved to what we expect.
    self.assertTrue(path.endswith('/.deps/ansicolors-1.0.2-py2-none-any.whl/colors.py'))
    # Check that the path is under the test's build root, so we know the pex was created there.
    self.assertTrue(path.startswith(os.path.realpath(get_buildroot())))
