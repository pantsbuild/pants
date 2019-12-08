# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.base.exceptions import TaskError
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.python.pex_build_util import (
    PexBuilderWrapper,
    has_python_sources,
    has_resources,
    is_python_target,
)
from pants.task.task import Task
from pants.util.dirutil import safe_concurrent_creation
from pants.util.ordered_set import OrderedSet


class GatherSources(Task):
    """Gather local Python sources.

    Creates an (unzipped) PEX on disk containing the local Python sources. This PEX can be merged
    with a requirements PEX to create a unified Python environment for running the relevant python
    code.
    """

    PYTHON_SOURCES = "python_sources"

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("GatherSources", 5)]

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (PexBuilderWrapper.Factory,)

    @classmethod
    def product_types(cls):
        return [cls.PYTHON_SOURCES]

    @classmethod
    def prepare(cls, options, round_manager):
        round_manager.require_data(PythonInterpreter)
        round_manager.optional_data("python")  # For codegen.

    def execute(self):
        targets = self._collect_source_targets()
        if not targets:
            return
        interpreter = self.context.products.get_data(PythonInterpreter)

        with self.invalidated(targets) as invalidation_check:
            pex = self._get_pex_for_versioned_targets(interpreter, invalidation_check.all_vts)
            self.context.products.register_data(self.PYTHON_SOURCES, pex)

    def _collect_source_targets(self):
        python_target_addresses = [
            p.address for p in self.context.targets(predicate=is_python_target)
        ]

        targets = OrderedSet()

        def collect_source_targets(target):
            if has_python_sources(target) or has_resources(target):
                targets.add(target)

        self.context.build_graph.walk_transitive_dependency_graph(
            addresses=python_target_addresses, work=collect_source_targets
        )

        return targets

    def _get_pex_for_versioned_targets(self, interpreter, versioned_targets):
        if versioned_targets:
            target_set_id = VersionedTargetSet.from_versioned_targets(
                versioned_targets
            ).cache_key.hash
        else:
            raise TaskError("Can't create pex in gather_sources: No python targets provided")
        source_pex_path = os.path.realpath(os.path.join(self.workdir, target_set_id))
        # Note that we check for the existence of the directory, instead of for invalid_vts,
        # to cover the empty case.
        if not os.path.isdir(source_pex_path):
            # Note that we use the same interpreter for all targets: We know the interpreter
            # is compatible (since it's compatible with all targets in play).
            with safe_concurrent_creation(source_pex_path) as safe_path:
                self._build_pex(interpreter, safe_path, [vt.target for vt in versioned_targets])
        return PEX(source_pex_path, interpreter=interpreter)

    def _build_pex(self, interpreter, path, targets):
        pex_builder = PexBuilderWrapper.Factory.create(
            builder=PEXBuilder(path=path, interpreter=interpreter, copy=True), log=self.context.log
        )

        for target in targets:
            pex_builder.add_sources_from(target)
        pex_builder.freeze()
