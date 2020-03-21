# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.tasks.python_tool_prep_base import PythonToolInstance, PythonToolPrepBase
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class Tool(PythonToolBase):
    options_scope = "test-tool"
    # TODO: make a fake pex tool instead of depending on a real python requirement!
    default_version = "pex==1.5.3"
    default_entry_point = "pex.bin.pex:main"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--needs-to-be-invoked-for-some-reason", type=bool, default=True)


class ToolInstance(PythonToolInstance):
    pass


class ToolPrep(PythonToolPrepBase):
    options_scope = "tool-prep-task"
    tool_subsystem_cls = Tool
    tool_instance_cls = ToolInstance

    def will_be_invoked(self):
        return Tool.scoped_instance(self).get_options().needs_to_be_invoked_for_some_reason


class ToolTask(Task):
    options_scope = "tool-task"

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(ToolPrep.tool_instance_cls)

    def execute(self):
        tool_for_pex = self.context.products.get_data(ToolPrep.tool_instance_cls)
        stdout, _, exit_code, _ = tool_for_pex.output(["--version"])
        assert re.match(r".*\.pex 1.5.3", stdout)
        assert 0 == exit_code


class PythonToolPrepTest(PythonTaskTestBase):
    @classmethod
    def task_type(cls):
        return ToolTask

    def _assert_tool_execution_for_python_version(self, use_py3=True):
        scope_string = "3" if use_py3 else "2"
        constraint_string = "CPython>=3" if use_py3 else "CPython<3"
        tool_prep_type = self.synthesize_task_subtype(ToolPrep, f"tp_scope_py{scope_string}")
        with temporary_dir() as tmp_dir:
            context = self.context(
                for_task_types=[tool_prep_type],
                for_subsystems=[Tool],
                options={
                    "": {"pants_bootstrapdir": tmp_dir},
                    "test-tool": {"interpreter_constraints": [constraint_string]},
                },
            )
            tool_prep_task = tool_prep_type(
                context, os.path.join(self.pants_workdir, f"tp_py{scope_string}")
            )
            tool_prep_task.execute()
            pex_tool = context.products.get_data(ToolPrep.tool_instance_cls)
            self.assertIsNotNone(pex_tool)
            # Check that the tool can be created and executed successfully.
            self.create_task(context).execute()
            # Check that our pex tool wrapper was constructed with the expected interpreter.
            self.assertTrue(pex_tool.interpreter.identity.matches(constraint_string))
            return pex_tool

    def test_tool_execution(self):
        """Test that python tools are fingerprinted by python interpreter."""
        py3_pex_tool = self._assert_tool_execution_for_python_version(use_py3=True)
        py3_pex_tool_path = py3_pex_tool.pex.path()
        self.assertTrue(os.path.isdir(py3_pex_tool_path))
        py2_pex_tool = self._assert_tool_execution_for_python_version(use_py3=False)
        py2_pex_tool_path = py2_pex_tool.pex.path()
        self.assertTrue(os.path.isdir(py2_pex_tool_path))
        self.assertNotEqual(py3_pex_tool_path, py2_pex_tool_path)

    def test_tool_noop(self):
        tool_prep_type = self.synthesize_task_subtype(ToolPrep, "tool_prep")
        context = self.context(
            for_task_types=[tool_prep_type],
            for_subsystems=[Tool],
            options={"test-tool": {"needs_to_be_invoked_for_some_reason": False}},
        )
        tool_prep_task = tool_prep_type(context, os.path.join(self.pants_workdir, "tool_prep_dir"))
        tool_prep_task.execute()
        self.assertIsNone(context.products.get_data(ToolPrep.tool_instance_cls))
