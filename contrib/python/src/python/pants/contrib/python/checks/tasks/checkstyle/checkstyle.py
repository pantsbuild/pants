# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

from packaging import version
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.build_environment import get_buildroot, pants_version
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_all
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.option.custom_types import file_option
from pants.python.pex_build_util import PexBuilderWrapper
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup
from pants.task.lint_task_mixin import LintTaskMixin
from pants.task.task import Task
from pants.util.collections import factory_dict
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_concurrent_creation
from pants.util.memo import memoized_classproperty, memoized_property
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from pkg_resources import DistributionNotFound, Environment, Requirement, WorkingSet

from pants.contrib.python.checks.checker import checker
from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import (
    default_subsystem_for_plugin,
)
from pants.contrib.python.checks.tasks.checkstyle.pycheck_subsystem import Pycheck
from pants.contrib.python.checks.tasks.checkstyle.pycodestyle_subsystem import PyCodeStyleSubsystem
from pants.contrib.python.checks.tasks.checkstyle.pyflakes_subsystem import FlakeCheckSubsystem


class Checkstyle(LintTaskMixin, Task):
    _PYTHON_SOURCE_EXTENSION = ".py"

    _CUSTOM_PLUGIN_SUBSYSTEMS = (
        PyCodeStyleSubsystem,
        FlakeCheckSubsystem,
    )

    @memoized_classproperty
    def plugin_subsystems(cls):
        subsystem_type_by_plugin_type = factory_dict(default_subsystem_for_plugin)
        subsystem_type_by_plugin_type.update(
            (subsystem_type.plugin_type(), subsystem_type)
            for subsystem_type in cls._CUSTOM_PLUGIN_SUBSYSTEMS
        )
        return tuple(
            subsystem_type_by_plugin_type[plugin_type] for plugin_type in checker.plugins()
        )

    @classmethod
    def subsystem_dependencies(cls):
        return (
            super().subsystem_dependencies()
            + cls.plugin_subsystems
            + (Pycheck, PexBuilderWrapper.Factory, PythonInterpreterCache, PythonSetup,)
        )

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("Checkstyle", 1)]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--severity",
            fingerprint=True,
            default="COMMENT",
            type=str,
            help="Only messages at this severity or higher are logged. [COMMENT WARNING ERROR].",
        )
        register(
            "--strict",
            fingerprint=True,
            type=bool,
            help="If enabled, have non-zero exit status for any nit at WARNING or higher.",
        )
        register(
            "--suppress",
            fingerprint=True,
            type=file_option,
            default=None,
            help="Takes a text file where specific rules on specific files will be skipped.",
        )
        register(
            "--fail",
            fingerprint=True,
            default=True,
            type=bool,
            help="Prevent test failure but still produce output for problems.",
        )
        register(
            "--interpreter-constraints-whitelist",
            fingerprint=True,
            type=list,
            help="A list of interpreter constraints for which matching targets will be linted "
            "in addition to targets that match the global interpreter constraints "
            "(either from defaults or pants.toml). If the user supplies an empty list, "
            "Pants will lint all targets in the target set, irrespective of the working "
            "set of compatibility constraints.",
        )

    @property
    def skip_execution(self):
        return Pycheck.global_instance().options.skip

    def _is_checked(self, target):
        return (
            not target.is_synthetic
            and isinstance(target, PythonTarget)
            and target.has_sources(self._PYTHON_SOURCE_EXTENSION)
        )

    _CHECKER_ADDRESS_SPEC = "contrib/python/src/python/pants/contrib/python/checks/checker"
    _CHECKER_REQ = "pantsbuild.pants.contrib.python.checks.checker=={}".format(pants_version())
    _CHECKER_ENTRYPOINT = "pants.contrib.python.checks.checker.checker:main"

    @memoized_property
    def checker_target(self):
        self.context.resolve(self._CHECKER_ADDRESS_SPEC)
        return self.context.build_graph.get_target(Address.parse(self._CHECKER_ADDRESS_SPEC))

    @memoized_property
    def _acceptable_interpreter_constraints(self):
        default_constraints = PythonSetup.global_instance().interpreter_constraints
        whitelisted_constraints = self.get_options().interpreter_constraints_whitelist
        # The user wants to lint everything.
        if whitelisted_constraints == []:
            return []
        # The user did not pass a whitelist option.
        elif whitelisted_constraints is None:
            whitelisted_constraints = ()
        return [version.parse(v) for v in default_constraints + whitelisted_constraints]

    def checker_pex(self, interpreter):
        # TODO(John Sirois): Formalize in pants.base?
        pants_dev_mode = os.environ.get("PANTS_DEV", "0") != "0"

        if pants_dev_mode:
            checker_id = self.checker_target.transitive_invalidation_hash()
        else:
            checker_id = hash_all([self._CHECKER_REQ])

        pex_path = os.path.join(self.workdir, "checker", checker_id, str(interpreter.identity))

        if not os.path.exists(pex_path):
            with self.context.new_workunit(name="build-checker"):
                with safe_concurrent_creation(pex_path) as chroot:
                    pex_builder = PexBuilderWrapper.Factory.create(
                        builder=PEXBuilder(path=chroot, interpreter=interpreter),
                        log=self.context.log,
                    )

                    # Constraining is required to guard against the case where the user
                    # has a pexrc file set.
                    pex_builder.add_interpreter_constraint(str(interpreter.identity.requirement))

                    if pants_dev_mode:
                        pex_builder.add_sources_from(self.checker_target)
                        req_libs = [
                            tgt
                            for tgt in self.checker_target.closure()
                            if isinstance(tgt, PythonRequirementLibrary)
                        ]

                        pex_builder.add_requirement_libs_from(req_libs=req_libs)
                    else:
                        try:
                            # The checker is already on sys.path, eg: embedded in pants.pex.
                            platform = Platform.current()
                            platform_name = platform.platform
                            env = Environment(
                                search_path=sys.path,
                                platform=platform_name,
                                python=interpreter.version_string,
                            )
                            working_set = WorkingSet(entries=sys.path)
                            for dist in working_set.resolve(
                                [Requirement.parse(self._CHECKER_REQ)], env=env
                            ):
                                pex_builder.add_direct_requirements(dist.requires())
                                # NB: We add the dist location instead of the dist itself to make sure its a
                                # distribution style pex knows how to package.
                                pex_builder.add_dist_location(dist.location)
                            pex_builder.add_direct_requirements([self._CHECKER_REQ])
                        except (DistributionNotFound, PEXBuilder.InvalidDistribution):
                            # We need to resolve the checker from a local or remote distribution repo.
                            pex_builder.add_resolved_requirements(
                                [PythonRequirement(self._CHECKER_REQ)]
                            )

                    pex_builder.set_entry_point(self._CHECKER_ENTRYPOINT)
                    pex_builder.freeze()

        return PEX(pex_path, interpreter=interpreter)

    def checkstyle(self, interpreter, sources):
        """Iterate over sources and run checker on each file.

        Files can be suppressed with a --suppress option which takes an xml file containing
        file paths that have exceptions and the plugins they need to ignore.

        :param sources: iterable containing source file names.
        :return: (int) number of failures
        """
        checker = self.checker_pex(interpreter)

        args = [
            "--root-dir={}".format(get_buildroot()),
            "--severity={}".format(self.get_options().severity),
        ]
        if self.get_options().suppress:
            args.append("--suppress={}".format(self.get_options().suppress))
        if self.get_options().strict:
            args.append("--strict")

        with temporary_file(binary_mode=False) as argfile:
            for plugin_subsystem in self.plugin_subsystems:
                options_blob = plugin_subsystem.global_instance().options_blob()
                if options_blob:
                    argfile.write(
                        "--{}-options={}\n".format(
                            plugin_subsystem.plugin_type().name(), options_blob
                        )
                    )
            argfile.write("\n".join(sources))
            argfile.close()

            args.append("@{}".format(argfile.name))

            with self.context.new_workunit(
                name="pythonstyle",
                labels=[WorkUnitLabel.TOOL, WorkUnitLabel.LINT],
                cmd=" ".join(checker.cmdline(args)),
            ) as workunit:
                return checker.run(
                    args=args, stdout=workunit.output("stdout"), stderr=workunit.output("stderr")
                )

    def _constraints_are_whitelisted(self, constraint_tuple):
        """Detect whether a tuple of compatibility constraints matches constraints imposed by the
        merged list of the global constraints from PythonSetup and a user-supplied whitelist."""
        if self._acceptable_interpreter_constraints == []:
            # The user wants to lint everything.
            return True
        return all(
            version.parse(constraint) in self._acceptable_interpreter_constraints
            for constraint in constraint_tuple
        )

    def execute(self):
        """"Run Checkstyle on all found non-synthetic source files."""
        python_tgts = self.context.targets(lambda tgt: isinstance(tgt, (PythonTarget)))
        if not python_tgts:
            return 0
        interpreter_cache = PythonInterpreterCache.global_instance()
        with self.invalidated(self.get_targets(self._is_checked)) as invalidation_check:
            failure_count = 0
            tgts_by_compatibility, _ = interpreter_cache.partition_targets_by_compatibility(
                [vt.target for vt in invalidation_check.invalid_vts]
            )
            for filters, targets in tgts_by_compatibility.items():
                sources = self.calculate_sources([tgt for tgt in targets])
                if sources:
                    allowed_interpreters = set(interpreter_cache.setup(filters=filters))
                    if not allowed_interpreters:
                        raise TaskError(
                            "No valid interpreters found for targets: {}\n(filters: {})".format(
                                targets, filters
                            )
                        )
                    interpreter = min(allowed_interpreters)
                    failure_count += self.checkstyle(interpreter, sources)
            if failure_count > 0 and self.get_options().fail:
                raise TaskError(
                    "{} Python Style issues found. You may try `./pants fmt <targets>`".format(
                        failure_count
                    )
                )
            return failure_count

    def calculate_sources(self, targets):
        """Generate a set of source files from the given targets."""
        sources = set()
        for target in targets:
            sources.update(
                source
                for source in target.sources_relative_to_buildroot()
                if source.endswith(self._PYTHON_SOURCE_EXTENSION)
            )
        return sources
