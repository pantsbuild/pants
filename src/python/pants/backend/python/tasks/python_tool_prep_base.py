# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import subprocess
from contextlib import contextmanager
from typing import Optional, Type

from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.base.build_environment import get_pants_cachedir
from pants.base.exceptions import TaskError
from pants.base.hash_utils import stable_json_sha1
from pants.base.workunit import WorkUnitLabel
from pants.python.pex_build_util import PexBuilderWrapper
from pants.python.python_requirement import PythonRequirement
from pants.task.task import Task
from pants.util.dirutil import safe_concurrent_creation
from pants.util.strutil import ensure_binary, safe_shlex_join


class PythonToolInstance:
    logger = logging.getLogger(__name__)

    def __init__(self, pex_path, interpreter):
        self._pex = PEX(pex_path, interpreter=interpreter)
        self._interpreter = interpreter

    @property
    def pex(self):
        return self._pex

    @property
    def interpreter(self):
        return self._interpreter

    def _pretty_cmdline(self, args):
        return safe_shlex_join(self._pex.cmdline(args))

    def output(self, args, stdin_payload=None, binary_mode=False, **kwargs):
        process = self._pex.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            with_chroot=False,
            blocking=False,
            **kwargs,
        )
        if stdin_payload is not None:
            stdin_payload = ensure_binary(stdin_payload)
        (stdout, stderr) = process.communicate(input=stdin_payload)
        if not binary_mode:
            stdout = stdout.decode()
            stderr = stderr.decode()
        return (stdout, stderr, process.returncode, self._pretty_cmdline(args))

    @contextmanager
    def run_with(self, workunit_factory, args, **kwargs):
        cmdline = self._pretty_cmdline(args)
        with workunit_factory(cmd=cmdline) as workunit:
            exit_code = self._pex.run(
                args,
                stdout=workunit.output("stdout"),
                stderr=workunit.output("stderr"),
                with_chroot=False,
                blocking=True,
                **kwargs,
            )
            yield cmdline, exit_code, workunit

    def run(self, *args, **kwargs):
        with self.run_with(*args, **kwargs) as (cmdline, exit_code, _):
            return cmdline, exit_code


# TODO: If `.will_be_invoked()` is not overridden, this python tool setup ends up eagerly generating
# each pex for each task in every goal which is transitively required by the command-line goals,
# even for tasks which no-op. This requires each pex for each relevant python tool to be buildable
# on the current host, even if it may never be intended to be invoked, unless the prep task is able
# to know whether it will be invoked in advance. Especially given the existing clear separation of
# concerns into PythonToolBase/PythonToolInstance/PythonToolPrepBase, this seems like an extremely
# ripe use case for some v2 rules for free caching and no-op when not required for the command-line
# goals.
class PythonToolPrepBase(Task):
    """Base class for tasks that resolve a python tool to be invoked out-of-process."""

    # Subclasses must set to a subclass of `pants.backend.python.subsystems.PythonToolBase`.
    tool_subsystem_cls: Optional[Type[PythonToolBase]] = None

    # Subclasses must set to a subclass of `PythonToolInstance`.  This is the type of the
    # product produced by this task.  It is distinct from the subsystem type so that multiple
    # instances of the same tool, possibly at different versions, can be resolved by different
    # prep tasks, if necessary.
    tool_instance_cls: Optional[Type[PythonToolInstance]] = None

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            cls.tool_subsystem_cls.scoped(cls),
            PexBuilderWrapper.Factory,
            PythonInterpreterCache,
        )

    @classmethod
    def product_types(cls):
        return [cls.tool_instance_cls]

    def _build_tool_pex(self, tool_subsystem, interpreter, pex_path):
        with safe_concurrent_creation(pex_path) as chroot:
            pex_builder = PexBuilderWrapper.Factory.create(
                builder=PEXBuilder(path=chroot, interpreter=interpreter), log=self.context.log
            )
            reqs = [PythonRequirement(r) for r in tool_subsystem.get_requirement_specs()]
            pex_builder.add_resolved_requirements(reqs=reqs, platforms=["current"])
            pex_builder.set_entry_point(tool_subsystem.get_entry_point())
            pex_builder.freeze()

    def _generate_fingerprinted_pex_path(self, tool_subsystem, interpreter):
        # `tool_subsystem.get_requirement_specs()` is a list, but order shouldn't actually matter. This
        # should probably be sorted, but it's possible a user could intentionally tweak order to work
        # around a particular requirement resolution resolve-order issue. In practice the lists are
        # expected to be mostly static, so we accept the risk of too-fine-grained caching creating lots
        # of pexes in the cache dir.
        specs_fingerprint = stable_json_sha1(tool_subsystem.get_requirement_specs())
        return os.path.join(
            get_pants_cachedir(),
            "python",
            str(interpreter.identity),
            self.fingerprint,
            f"{tool_subsystem.options_scope}-{specs_fingerprint}.pex",
        )

    def will_be_invoked(self):
        """Predicate which can be overridden to allow tool creation to no-op when not needed."""
        return True

    def execute(self):
        if not self.will_be_invoked():
            return

        tool_subsystem = self.tool_subsystem_cls.scoped_instance(self)

        interpreter_cache = PythonInterpreterCache.global_instance()
        interpreters = interpreter_cache.setup(filters=tool_subsystem.get_interpreter_constraints())
        if not interpreters:
            raise TaskError(
                "Found no Python interpreter capable of running the {} tool with "
                "constraints {}".format(
                    tool_subsystem.options_scope, tool_subsystem.get_interpreter_constraints()
                )
            )
        interpreter = min(interpreters)

        pex_path = self._generate_fingerprinted_pex_path(tool_subsystem, interpreter)
        if not os.path.exists(pex_path):
            with self.context.new_workunit(
                name=f"create-{tool_subsystem.options_scope}-pex", labels=[WorkUnitLabel.PREP]
            ):
                self._build_tool_pex(
                    tool_subsystem=tool_subsystem, interpreter=interpreter, pex_path=pex_path
                )

        tool_instance = self.tool_instance_cls(pex_path, interpreter)
        self.context.products.register_data(self.tool_instance_cls, tool_instance)
