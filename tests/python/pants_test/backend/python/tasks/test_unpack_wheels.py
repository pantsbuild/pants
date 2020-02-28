# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import re

from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.unpacked_whls import UnpackedWheels
from pants.backend.python.tasks.unpack_wheels import UnpackWheels, UnpackWheelsFingerprintStrategy
from pants.python.python_requirement import PythonRequirement
from pants.task.unpack_remote_sources_base import UnpackedArchives
from pants.testutil.task_test_base import TaskTestBase
from pants.util.collections import assert_single_element


class UnpackWheelsTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return UnpackWheels

    def _make_req_library(self, requirement):
        return self.make_target(
            spec="unpack/whls:foo-whls",
            target_type=PythonRequirementLibrary,
            requirements=[requirement],
        )

    def _make_unpacked_wheel(self, requirement, include_patterns, module_name="foo", **kwargs):
        reqlib = self._make_req_library(requirement)
        return self.make_target(
            spec="unpack:foo",
            target_type=UnpackedWheels,
            libraries=[reqlib.address.spec],
            module_name=module_name,
            include_patterns=include_patterns,
            **kwargs
        )

    def test_unpack_wheels_fingerprint_strategy(self):
        fingerprint_strategy = UnpackWheelsFingerprintStrategy()

        make_unpacked_wheel = functools.partial(self._make_unpacked_wheel, include_patterns=["bar"])
        req1 = PythonRequirement("com.example.bar==0.0.1")
        target = make_unpacked_wheel(req1)
        fingerprint1 = fingerprint_strategy.compute_fingerprint(target)

        # Now, replace the build file with a different version.
        self.reset_build_graph()
        target = make_unpacked_wheel(PythonRequirement("com.example.bar==0.0.2"))
        fingerprint2 = fingerprint_strategy.compute_fingerprint(target)
        self.assertNotEqual(fingerprint1, fingerprint2)

        # Go back to the original library.
        self.reset_build_graph()
        target = make_unpacked_wheel(req1)
        fingerprint3 = fingerprint_strategy.compute_fingerprint(target)

        self.assertEqual(fingerprint1, fingerprint3)

    def _assert_unpacking(self, module_name):
        # TODO: figure out how to generate a nice fake wheel that the pex resolve will accept instead of
        # depending on a real wheel!
        pex_requirement = PythonRequirement("pex==1.5.3")
        unpacked_wheel_tgt = self._make_unpacked_wheel(
            pex_requirement,
            include_patterns=["pex/pex.py", "pex/__init__.py"],
            module_name=module_name,
            # TODO: `within_data_subdir` is only tested implicitly by the tensorflow_custom_op target
            # in examples/! Make a fake wheel, resolve it, and test that `within_data_subdir`
            # descends into the correct directory!
            within_data_subdir=None,
        )
        context = self.context(target_roots=[unpacked_wheel_tgt])
        unpack_task = self.create_task(context)
        unpack_task.execute()

        expected_files = {"pex/__init__.py", "pex/pex.py"}

        with unpack_task.invalidated([unpacked_wheel_tgt]) as invalidation_check:
            vt = assert_single_element(invalidation_check.all_vts)
            self.assertEqual(vt.target, unpacked_wheel_tgt)
            archives = context.products.get_data(UnpackedArchives, dict)[vt.target]
            self.assertEqual(expected_files, set(archives.found_files))

    def test_unpacking(self):
        self._assert_unpacking(module_name="pex")

    def test_unpack_missing_module_name(self):
        with self.assertRaisesRegex(
            UnpackWheels.WheelUnpackingError,
            re.escape(
                "Error extracting wheel for target UnpackedWheels(unpack:foo): Exactly one dist was expected to match name not-a-real-module"
            ),
        ):
            self._assert_unpacking(module_name="not-a-real-module")
