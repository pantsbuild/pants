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
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks2.resolve_requirements import ResolveRequirements
from pants.base.build_environment import get_buildroot
from pants.python.python_repos import PythonRepos
from pants.util.contextutil import temporary_file
from pants_test.tasks.task_test_base import TaskTestBase


class ResolveRequirementsTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return ResolveRequirements

  def test_resolve_simple_requirements(self):
    noreqs_tgt = self._fake_target('noreqs', [])
    ansicolors_tgt = self._fake_target('ansicolors', ['ansicolors==1.0.2'])

    # Check that the module is unavailable unless specified as a requirement (proves that
    # the requirement isn't sneaking in some other way, which would render the remainder
    # of this test moot.)
    _, stderr_data = self._exercise_module(self._resolve_requirements([noreqs_tgt]), 'colors')
    self.assertIn('ImportError: No module named colors', stderr_data)

    # Check that the module is available if specified as a requirement.
    stdout_data, stderr_data = self._exercise_module(self._resolve_requirements([ansicolors_tgt]),
                                                     'colors')
    self.assertEquals('', stderr_data.strip())

    path = stdout_data.strip()
    # Check that the requirement resolved to what we expect.
    self.assertTrue(path.endswith('/.deps/ansicolors-1.0.2-py2-none-any.whl/colors.py'))
    # Check that the path is under the test's build root, so we know the pex was created there.
    self.assertTrue(path.startswith(os.path.realpath(get_buildroot())))

  def test_resolve_multiplatform_requirements(self):
    cffi_tgt = self._fake_target('cffi', ['cffi==1.9.1'])

    pex = self._resolve_requirements([cffi_tgt], {
      'python-setup': {
        # We have 'current' so we can import the module in order to get the path to it.
        # The other platforms (one of which may happen to be the same as current) are what we
        # actually test the presence of.
        'platforms': ['current', 'macosx-10.10-x86_64', 'manylinux1_i686', 'win_amd64']
      }
    })
    stdout_data, stderr_data = self._exercise_module(pex, 'cffi')
    self.assertEquals('', stderr_data.strip())

    path = stdout_data.strip()
    wheel_dir = os.path.join(path[0:path.find('{sep}.deps{sep}'.format(sep=os.sep))], '.deps')
    wheels = set(os.listdir(wheel_dir))

    def name_and_platform(whl):
      # The wheel filename is of the format
      # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
      # See https://www.python.org/dev/peps/pep-0425/.
      # We don't care about the python or abi versions (they depend on what we're currently
      # running on), we just want to make sure we have all the platforms we expect.
      parts = os.path.splitext(whl)[0].split('-')
      return '{}-{}'.format(parts[0], parts[1]), parts[-1]

    names_and_platforms = set(name_and_platform(w) for w in wheels)
    expected_name_and_platforms = {
      # Note that we don't check for 'current' because if there's no published wheel for the
      # current platform we may end up with a wheel for a compatible platform (e.g., if there's no
      # wheel for macosx_10_11_x86_64, 'current' will be satisfied by macosx_10_10_x86_64).
      # This is technically also true for the hard-coded platforms we list below, but we chose
      # those and we happen to know that cffi wheels exist for them.  Whereas we have no such
      # advance knowledge for the current platform, whatever that might be in the future.
      ('cffi-1.9.1', 'macosx_10_10_x86_64'),
      ('cffi-1.9.1', 'manylinux1_i686'),
      ('cffi-1.9.1', 'win_amd64'),
    }

    # pycparser is a dependency of cffi only on CPython.  We might as well check for it,
    # as extra verification that we correctly fetch transitive dependencies.
    if PythonInterpreter.get().identity.interpreter == 'CPython':
      expected_name_and_platforms.add(('pycparser-2.17', 'any'))

    self.assertTrue(expected_name_and_platforms.issubset(names_and_platforms),
                    '{} is not a subset of {}'.format(expected_name_and_platforms,
                                                      names_and_platforms))

    # Check that the path is under the test's build root, so we know the pex was created there.
    self.assertTrue(path.startswith(os.path.realpath(get_buildroot())))

  def _fake_target(self, spec, requirement_strs):
    requirements = [PythonRequirement(r) for r in requirement_strs]
    return self.make_target(spec=spec, target_type=PythonRequirementLibrary,
                            requirements=requirements)

  def _resolve_requirements(self, target_roots, options=None):
    context = self.context(target_roots=target_roots, options=options,
                           for_subsystems=[PythonSetup, PythonRepos])

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

  def _exercise_module(self, pex, expected_module):
    with temporary_file() as f:
      f.write('import {m}; print({m}.__file__)'.format(m=expected_module))
      f.close()
      proc = pex.run(args=[f.name], blocking=False,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      return proc.communicate()
