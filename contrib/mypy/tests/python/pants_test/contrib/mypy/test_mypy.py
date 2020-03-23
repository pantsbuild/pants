# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import Any, Dict, List, Optional, cast

from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.target import Target
from pants.testutil.task_test_base import TaskTestBase

from pants.contrib.mypy.tasks.mypy_task import MypyTask


class MyPyWhitelistMechanismTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return MypyTask

    def make_python_target(
        self, spec: str, *, typed: bool = False, dependencies: Optional[List[Target]] = None,
    ) -> Target:
        kwargs: Dict[str, Any] = {}
        if typed:
            kwargs["tags"] = ["type_checked"]
        if dependencies:
            kwargs["dependencies"] = dependencies
        return cast(Target, self.make_target(spec, PythonLibrary, **kwargs))

    def run_task_and_capture_warnings(
        self, *, target_roots: List[Target], enable_whitelist: bool = True
    ) -> List[str]:
        self.set_options(verbose=True)
        if enable_whitelist:
            self.set_options(whitelist_tag_name="type_checked")
        context = self.context(target_roots=target_roots)
        task = self.create_task(context)
        with self.captured_logging(level=logging.WARNING) as captured:
            task.execute()
        return cast(List[str], captured.warnings())

    def assert_no_warning(self, captured_warnings: List[str]) -> None:
        self.assertFalse(captured_warnings)

    def assert_warning(
        self, captured_warnings: List[str], *, expected_targets: List[Target]
    ) -> None:
        self.assertTrue(captured_warnings)
        for tgt in expected_targets:
            self.assertIn(tgt.address.spec, captured_warnings[0])

    def test_no_whitelist(self) -> None:
        t1 = self.make_python_target("t1")
        captured_warnings = self.run_task_and_capture_warnings(
            target_roots=[t1], enable_whitelist=False
        )
        self.assert_no_warning(captured_warnings)

    def test_whitelisted_target_roots(self) -> None:
        t1 = self.make_python_target("t1", typed=True)
        t2 = self.make_python_target("t2", typed=True)
        captured_warnings = self.run_task_and_capture_warnings(target_roots=[t1, t2])
        self.assert_no_warning(captured_warnings)

    def test_target_roots_not_whitelisted(self) -> None:
        t1 = self.make_python_target("t1")
        t2 = self.make_python_target("t2")
        captured_warnings = self.run_task_and_capture_warnings(target_roots=[t1, t2])
        self.assert_no_warning(captured_warnings)

    def test_whitelisted_dependency(self) -> None:
        t1 = self.make_python_target("t1", typed=True)
        t2 = self.make_python_target("t2", typed=True, dependencies=[t1])
        captured_warnings = self.run_task_and_capture_warnings(target_roots=[t2])
        self.assert_no_warning(captured_warnings)

    def test_dependency_not_whitelisted(self) -> None:
        t1 = self.make_python_target("t1")
        t2 = self.make_python_target("t2", typed=True, dependencies=[t1])
        captured_warnings = self.run_task_and_capture_warnings(target_roots=[t2])
        self.assert_warning(captured_warnings, expected_targets=[t1])

    def test_untyped_target_root_also_dependency(self) -> None:
        t1 = self.make_python_target("t1")
        t2 = self.make_python_target("t2", typed=True, dependencies=[t1])
        captured_warnings = self.run_task_and_capture_warnings(target_roots=[t1, t2])
        self.assert_warning(captured_warnings, expected_targets=[t1])
