# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.backend.codegen.antlr.python.python_antlr_library import PythonAntlrLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import target_option
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdir, touch
from pants.util.memo import memoized_method

logger = logging.getLogger(__name__)


_ANTLR4_REV = "4.8"


# TODO: Refactor this and AntlrJavaGen to share a common base class with most of the functionality.
# In particular, doing so will add antlr4 and timestamp stripping support for Python.
# However, this refactoring will only  make sense once we modify PythonAntlrLibrary
# as explained below.
class AntlrPyGen(SimpleCodegenTask, NailgunTask):
    """Generate Python source code from ANTLR grammar files."""

    gentarget_type = PythonAntlrLibrary

    sources_globs = ("**/*.py",)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # The ANTLR compiler.
        cls.register_jvm_tool(
            register,
            "antlr4",
            classpath=[JarDependency(org="org.antlr", name="antlr4", rev=_ANTLR4_REV)],
            classpath_spec="//:antlr4-{}".format(_ANTLR4_REV),
        )
        # The ANTLR runtime python deps.
        register(
            "--antlr4-deps",
            advanced=True,
            type=list,
            member_type=target_option,
            help="A list of address specs pointing to dependencies of ANTLR4 generated code.",
        )

    def find_sources(self, target, target_dir):
        # Ignore .tokens files.
        sources = super().find_sources(target, target_dir)
        return [source for source in sources if source.endswith(".py")]

    def is_gentarget(self, target):
        return isinstance(target, PythonAntlrLibrary)

    def synthetic_target_type(self, target):
        return PythonLibrary

    def synthetic_target_extra_dependencies(self, target, target_workdir):
        return self._deps()

    @property
    def _copy_target_attributes(self):
        return super()._copy_target_attributes + ["compatibility"]

    @memoized_method
    def _deps(self):
        antlr4_deps = self.get_options().antlr4_deps
        return list(self.resolve_deps(antlr4_deps))

    # This checks to make sure that all of the sources have an identical package source structure, and
    # if they do, uses that as the package. If they are different, then the user will need to set the
    # package as it cannot be correctly inferred.
    def _get_sources_package(self, target):
        parents = {os.path.dirname(source) for source in target.sources_relative_to_source_root()}
        if len(parents) != 1:
            raise self.AmbiguousPackageError(
                "Antlr sources in multiple directories, cannot infer "
                "package. Please set package member in antlr target."
            )
        return parents.pop().replace("/", ".")

    def execute_codegen(self, target, target_workdir):
        args = ["-o", target_workdir]
        compiler = target.compiler
        if compiler == "antlr3":
            java_main = "org.antlr.Tool"
        elif compiler == "antlr4":
            args.append("-Dlanguage=Python3")
            java_main = "org.antlr.v4.Tool"
        else:
            raise TaskError("Unsupported ANTLR compiler: {}".format(compiler))

        antlr_classpath = self.tool_classpath(compiler)
        sources = self._calculate_sources([target])
        args.extend(sources)
        result = self.runjava(
            classpath=antlr_classpath, main=java_main, args=args, workunit_name="antlr"
        )
        if result != 0:
            raise TaskError("java {} ... exited non-zero ({})".format(java_main, result))

    def _calculate_sources(self, targets):
        sources = set()

        def collect_sources(tgt):
            if self.is_gentarget(tgt):
                sources.update(tgt.sources_relative_to_buildroot())

        for target in targets:
            target.walk(collect_sources)
        return sources

    # Antlr3 doesn't create the package structure, so we have to do so, and then tell
    # it where to write the files.
    def _create_package_structure(self, workdir, module):
        path = workdir
        for d in module.split("."):
            path = os.path.join(path, d)
            # Supposedly we get handed a clean workdir, but I'm not sure that's true.
            safe_mkdir(path, clean=True)
            touch(os.path.join(path, "__init__.py"))
        return path
