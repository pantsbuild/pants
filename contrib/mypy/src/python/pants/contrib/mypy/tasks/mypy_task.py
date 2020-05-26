# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path
from textwrap import dedent
from typing import Iterable, List, Set

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.base import hash_utils
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.contextutil import temporary_file, temporary_file_path
from pants.util.memo import memoized_property
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_info import PexInfo

from pants.contrib.mypy.subsystems.subsystem import MyPy


class MypyTaskError(TaskError):
    """Indicates a TaskError from a failing MyPy run."""


class MypyTask(LintTaskMixin, ResolveRequirementsTaskBase):
    """Invoke the mypy static type analyzer for Python.

    Mypy lint task filters out target_roots that are not properly tagged according to
    --whitelisted-tag-name (defaults to None, and no filtering occurs if this option is 'None'),
    and executes MyPy on targets in context from whitelisted target roots.
    (if any transitive targets from the filtered roots are not whitelisted, a warning
    will be printed.)

    'In context' meaning in the sub-graph where a whitelisted target is the root
    """

    _MYPY_COMPATIBLE_INTERPRETER_CONSTRAINT = ">=3.5"
    _PYTHON_SOURCE_EXTENSION = ".py"

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(PythonInterpreter)
        if options.include_requirements:
            round_manager.require_data(ResolveRequirements.REQUIREMENTS_PEX)

    @classmethod
    def register_options(cls, register):
        register(
            "--include-requirements",
            type=bool,
            default=False,
            help="Whether to include the transitive requirements of targets being checked. This is"
            "useful if those targets depend on mypy plugins or distributions that provide "
            "type stubs that should be active in the check.",
        )
        register(
            "--whitelist-tag-name",
            default=None,
            help="Tag name to identify Python targets to execute MyPy",
        )
        register(
            "--verbose",
            type=bool,
            default=False,
            help="Extra detail showing non-whitelisted targets",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (PythonInterpreterCache, MyPy)

    @property
    def skip_execution(self):
        return self._mypy_subsystem.options.skip

    def find_mypy_interpreter(self):
        interpreters = self._interpreter_cache.setup(
            filters=[self._MYPY_COMPATIBLE_INTERPRETER_CONSTRAINT]
        )
        return min(interpreters) if interpreters else None

    @staticmethod
    def is_non_synthetic_python_target(target):
        return not target.is_synthetic and isinstance(
            target, (PythonLibrary, PythonBinary, PythonTests)
        )

    @staticmethod
    def is_python_target(target):
        return isinstance(target, PythonTarget)

    def _check_for_untagged_dependencies(
        self, *, tagged_target_roots: Iterable[Target], tag_name: str
    ) -> None:
        untagged_dependencies = {
            tgt
            for tgt in Target.closure_for_targets(target_roots=tagged_target_roots)
            if tag_name not in tgt.tags and self.is_non_synthetic_python_target(tgt)
        }
        if not untagged_dependencies:
            return
        formatted_targets = "\n".join(tgt.address.spec for tgt in sorted(untagged_dependencies))
        self.context.log.warn(
            f"[WARNING]: The following targets are not marked with the tag name `{tag_name}`, "
            f"but are dependencies of targets that are type checked. MyPy will check these dependencies, "
            f"inferring `Any` where possible. You are encouraged to properly type check "
            f"these dependencies.\n{formatted_targets}"
        )

    def _calculate_python_sources(self, target_roots: Iterable[Target]) -> List[str]:
        """Filter targets to generate a set of source files from the given targets."""
        all_targets = {
            tgt
            for tgt in Target.closure_for_targets(target_roots=target_roots)
            if self.is_non_synthetic_python_target(tgt)
        }
        whitelist_tag_name = self.get_options().whitelist_tag_name
        if whitelist_tag_name:
            tagged_targets = {tgt for tgt in all_targets if whitelist_tag_name in tgt.tags}
            eval_targets = tagged_targets
            if self.get_options().verbose:
                self._check_for_untagged_dependencies(
                    tagged_target_roots={tgt for tgt in tagged_targets if tgt in target_roots},
                    tag_name=whitelist_tag_name,
                )
        else:
            eval_targets = all_targets

        sources: Set[str] = set()
        for target in eval_targets:
            sources.update(
                source
                for source in target.sources_relative_to_buildroot()
                if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
            )
        return list(sorted(sources))

    def _collect_source_roots(self):
        # Collect the set of directories in which there are Python sources (whether part of
        # the target roots or transitive dependencies.)
        source_roots = set()
        for target in self.context.targets(self.is_python_target):
            if not target.has_sources(self._PYTHON_SOURCE_EXTENSION):
                continue
            source_roots.add(target.target_base)
        return source_roots

    @memoized_property
    def _interpreter_cache(self):
        return PythonInterpreterCache.global_instance()

    @memoized_property
    def _mypy_subsystem(self):
        return MyPy.global_instance()

    def _get_mypy_pex(self, py3_interpreter: PythonInterpreter, *extra_pexes: PEX) -> PEX:
        mypy_version = self._mypy_subsystem.options.version
        extras_hash = hash_utils.hash_all(
            hash_utils.hash_dir(Path(extra_pex.path())) for extra_pex in extra_pexes
        )

        path = Path(self.workdir, str(py3_interpreter.identity), f"{mypy_version}-{extras_hash}")
        pex_dir = str(path)
        if not path.is_dir():
            mypy_requirement_pex = self.resolve_requirement_strings(py3_interpreter, [mypy_version])
            pex_info = PexInfo.default()
            pex_info.entry_point = "pants_mypy_launcher"
            with self.merged_pex(
                path=pex_dir,
                pex_info=pex_info,
                interpreter=py3_interpreter,
                pexes=[mypy_requirement_pex, *extra_pexes],
            ) as builder:
                with temporary_file(binary_mode=False) as exe_fp:
                    # MyPy searches for types for a package in packages containing a `py.types`
                    # marker file or else in a sibling `<package>-stubs` package as per PEP-0561.
                    # Going further than that PEP, MyPy restricts its search to `site-packages`.
                    # Since PEX deliberately isolates itself from `site-packages` as part of its
                    # raison d'etre, we monkey-patch `site.getsitepackages` to look inside the
                    # scrubbed PEX sys.path before handing off to `mypy`.
                    #
                    # As a complication, MyPy does its own validation to ensure packages aren't
                    # both available in site-packages and on the PYTHONPATH. As such, we elide all
                    # PYTHONPATH entries from artificial site-packages we set up since MyPy will
                    # manually scan PYTHONPATH outside this PEX to find packages.
                    #
                    # See:
                    #   https://mypy.readthedocs.io/en/stable/installed_packages.html#installed-packages
                    #   https://www.python.org/dev/peps/pep-0561/#stub-only-packages
                    exe_fp.write(
                        dedent(
                            """
                            import os
                            import runpy
                            import site
                            import sys

                            PYTHONPATH = frozenset(
                                os.path.realpath(p)
                                for p in os.environ.get('PYTHONPATH', '').split(os.pathsep)
                            )

                            site.getsitepackages = lambda: [
                                p for p in sys.path if os.path.realpath(p) not in PYTHONPATH
                            ]

                            runpy.run_module('mypy', run_name='__main__')
                            """
                        )
                    )
                    exe_fp.flush()
                    builder.set_executable(
                        filename=exe_fp.name, env_filename=f"{pex_info.entry_point}.py"
                    )
                builder.freeze(bytecode_compile=False)

        return PEX(pex_dir, py3_interpreter)

    def execute(self):
        mypy_interpreter = self.find_mypy_interpreter()
        if not mypy_interpreter:
            raise TaskError(
                f"Unable to find a Python {self._MYPY_COMPATIBLE_INTERPRETER_CONSTRAINT} "
                f"interpreter (required for mypy)."
            )

        sources = self._calculate_python_sources(self.context.target_roots)
        if not sources:
            self.context.log.debug("No Python sources to check.")
            return

        # Determine interpreter used by the sources so we can tell mypy.
        interpreter_for_targets = self._interpreter_cache.select_interpreter_for_targets(
            self.context.target_roots
        )
        if not interpreter_for_targets:
            raise TaskError("No Python interpreter compatible with specified sources.")

        extra_pexes = []
        if self.get_options().include_requirements:
            if interpreter_for_targets.identity.matches(
                self._MYPY_COMPATIBLE_INTERPRETER_CONSTRAINT
            ):
                extra_pexes.append(
                    self.context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX)
                )
                mypy_interpreter = interpreter_for_targets
            else:
                self.context.log.warn(
                    f"The --include-requirements option is set, but the current target's requirements have "
                    f"been resolved for {interpreter_for_targets.identity} which is not compatible with mypy "
                    f"which needs {self._MYPY_COMPATIBLE_INTERPRETER_CONSTRAINT}: omitting resolved "
                    f"requirements from the mypy PYTHONPATH."
                )

        with temporary_file_path() as sources_list_path:
            with open(sources_list_path, "w") as f:
                for source in sources:
                    f.write(f"{source}\n")
            # Construct the mypy command line.
            cmd = [f"--python-version={interpreter_for_targets.identity.python}"]

            config = self._mypy_subsystem.options.config
            if config:
                cmd.append(f"--config-file={os.path.join(get_buildroot(), config)}")
            cmd.extend(self._mypy_subsystem.options.args)
            cmd.append(f"@{sources_list_path}")

            with self.context.new_workunit(name="create_mypy_pex", labels=[WorkUnitLabel.PREP]):
                mypy_pex = self._get_mypy_pex(mypy_interpreter, *extra_pexes)

            # Collect source roots for the targets being checked.
            buildroot = Path(get_buildroot())
            sources_path = os.pathsep.join(
                str(buildroot.joinpath(root)) for root in self._collect_source_roots()
            )

            # Execute mypy.
            with self.context.new_workunit(
                name="check",
                labels=[WorkUnitLabel.TOOL, WorkUnitLabel.RUN],
                cmd=" ".join(mypy_pex.cmdline(cmd)),
            ) as workunit:
                returncode = mypy_pex.run(
                    cmd,
                    env=dict(PYTHONPATH=sources_path, PEX_INHERIT_PATH="fallback"),
                    stdout=workunit.output("stdout"),
                    stderr=workunit.output("stderr"),
                )
                if returncode != 0:
                    raise MypyTaskError(f"mypy failed: code={returncode}")
