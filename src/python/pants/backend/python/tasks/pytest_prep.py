# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pkg_resources
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase
from pants.util.memo import memoized_classproperty


class PytestPrep(PythonExecutionTaskBase):
    """Prepares a PEX binary for the current test context with `pytest` as its entry-point."""

    class PytestBinary:
        """A `pytest` PEX binary with an embedded default (empty) `pytest.ini` config file."""

        @staticmethod
        def make_plugin_name(name):
            return "__{}_{}_plugin__".format(__name__.replace(".", "_"), name)

        @memoized_classproperty
        def coverage_plugin_module(cls):
            """Return the name of the coverage plugin module embedded in this pytest binary.

            :rtype: str
            """
            return cls.make_plugin_name("coverage")

        @memoized_classproperty
        def pytest_plugin_module(cls):
            """Return the name of the pytest plugin module embedded in this pytest binary.

            :rtype: str
            """
            return cls.make_plugin_name("pytest")

        def __init__(self, interpreter, pex):
            # Here we hack around `coverage.cmdline` nuking the 0th element of `sys.path` (our root pex)
            # by ensuring, the root pex is on the sys.path twice.
            # See: https://github.com/nedbat/coveragepy/issues/715
            pex_path = pex.path()
            pex_info = PexInfo.from_pex(pex_path)
            pex_info.merge_pex_path(pex_path)  # We're now on the sys.path twice.
            PEXBuilder(pex_path, interpreter=interpreter, pex_info=pex_info).freeze(
                bytecode_compile=False
            )
            self._pex = PEX(pex=pex_path, interpreter=interpreter)
            self._interpreter = interpreter

        @property
        def pex(self):
            """Return the loose-source py.test binary PEX.

            :rtype: :class:`pex.pex.PEX`
            """
            return self._pex

        @property
        def interpreter(self):
            """Return the interpreter used to build this PEX.

            :rtype: :class:`pex.interpreter.PythonInterpreter`
            """
            return self._interpreter

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("PytestPrep", 2)]

    @classmethod
    def product_types(cls):
        return [cls.PytestBinary]

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (PyTest,)

    @classmethod
    def _module_resource(cls, module_name, resource_relpath):
        return cls.ExtraFile(
            path=f"{module_name}.py",
            content=pkg_resources.resource_string(__name__, resource_relpath),
        )

    def extra_files(self):
        yield self._module_resource(self.PytestBinary.pytest_plugin_module, "pytest/plugin.py")
        yield self._module_resource(self.PytestBinary.coverage_plugin_module, "coverage/plugin.py")

    def extra_requirements(self):
        return PyTest.global_instance().get_requirement_strings()

    def execute(self):
        if not self.context.targets(lambda t: isinstance(t, PythonTests)):
            return
        pex_info = PexInfo.default()
        pex_info.entry_point = "pytest"
        pytest_binary = self.create_pex(pex_info)
        interpreter = self.context.products.get_data(PythonInterpreter)
        self.context.products.register_data(
            self.PytestBinary, self.PytestBinary(interpreter, pytest_binary)
        )
