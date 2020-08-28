# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from io import StringIO
from pathlib import PurePath
from tempfile import mkdtemp
from typing import Any, Dict, Iterable, Mapping, Optional, Type, TypeVar, Union, cast

from pants.base.build_root import BuildRoot
from pants.base.specs_parser import SpecsParser
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.fs import PathGlobs, PathGlobsAndRoot, Snapshot, Workspace
from pants.engine.goal import Goal
from pants.engine.internals.native import Native
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.process import InteractiveRunner
from pants.engine.rules import QueryRule, Rule
from pants.engine.target import Target, WrappedTarget
from pants.init.engine_initializer import EngineInitializer
from pants.option.global_options import ExecutionOptions, GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.source import source_root
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import recursive_dirname, safe_file_dump, safe_mkdir, safe_open
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

_P = TypeVar("_P")


@dataclass(frozen=True)
class GoalRuleResult:
    exit_code: int
    stdout: str
    stderr: str

    @staticmethod
    def noop() -> "GoalRuleResult":
        return GoalRuleResult(0, stdout="", stderr="")


@frozen_after_init
@dataclass(unsafe_hash=True)
class RuleRunner:
    build_root: str
    build_config: BuildConfiguration
    scheduler: SchedulerSession

    def __init__(
        self,
        *,
        rules: Optional[Iterable] = None,
        target_types: Optional[Iterable[Type[Target]]] = None,
        objects: Optional[Dict[str, Any]] = None,
        context_aware_object_factories: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.build_root = os.path.realpath(mkdtemp(suffix="_BUILD_ROOT"))
        safe_mkdir(self.build_root, clean=True)
        safe_mkdir(self.pants_workdir)
        BuildRoot().path = self.build_root

        # TODO: Redesign rule registration for tests to be more ergonomic and to make this less
        #  special-cased.
        all_rules = (
            *(rules or ()),
            *source_root.rules(),
            QueryRule(WrappedTarget, (Address, OptionsBootstrapper)),
        )
        build_config_builder = BuildConfiguration.Builder()
        build_config_builder.register_aliases(
            BuildFileAliases(
                objects=objects, context_aware_object_factories=context_aware_object_factories
            )
        )
        build_config_builder.register_rules(all_rules)
        build_config_builder.register_target_types(target_types or ())
        self.build_config = build_config_builder.create()

        options_bootstrapper = OptionsBootstrapper.create(
            env={}, args=["--pants-config-files=[]"], allow_pantsrc=False
        )
        global_options = options_bootstrapper.bootstrap_options.for_global_scope()
        local_store_dir = global_options.local_store_dir
        local_execution_root_dir = global_options.local_execution_root_dir
        named_caches_dir = global_options.named_caches_dir

        graph_session = EngineInitializer.setup_graph_extended(
            pants_ignore_patterns=[],
            use_gitignore=False,
            local_store_dir=local_store_dir,
            local_execution_root_dir=local_execution_root_dir,
            named_caches_dir=named_caches_dir,
            native=Native(),
            options_bootstrapper=options_bootstrapper,
            build_root=self.build_root,
            build_configuration=self.build_config,
            execution_options=ExecutionOptions.from_bootstrap_options(global_options),
        ).new_session(build_id="buildid_for_test", should_report_workunits=True)
        self.scheduler = graph_session.scheduler_session

    @property
    def pants_workdir(self) -> str:
        return os.path.join(self.build_root, ".pants.d")

    @property
    def rules(self) -> FrozenOrderedSet[Rule]:
        return self.build_config.rules

    @property
    def target_types(self) -> FrozenOrderedSet[Type[Target]]:
        return self.build_config.target_types

    def request_product(self, product_type: Type[_P], subjects: Iterable[Any]) -> _P:
        result = assert_single_element(
            self.scheduler.product_request(product_type, [Params(*subjects)])
        )
        return cast(_P, result)

    def run_goal_rule(
        self,
        goal: Type[Goal],
        *,
        global_args: Optional[Iterable[str]] = None,
        args: Optional[Iterable[str]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> GoalRuleResult:
        options_bootstrapper = create_options_bootstrapper(
            args=(*(global_args or []), goal.name, *(args or [])),
            env=env,
        )

        raw_specs = options_bootstrapper.get_full_options(
            [*GlobalOptions.known_scope_infos(), *goal.subsystem_cls.known_scope_infos()]
        ).specs
        specs = SpecsParser(self.build_root).parse_specs(raw_specs)

        stdout, stderr = StringIO(), StringIO()
        console = Console(stdout=stdout, stderr=stderr)

        exit_code = self.scheduler.run_goal_rule(
            goal,
            Params(
                specs,
                console,
                options_bootstrapper,
                Workspace(self.scheduler),
                InteractiveRunner(self.scheduler),
            ),
        )

        console.flush()
        return GoalRuleResult(exit_code, stdout.getvalue(), stderr.getvalue())

    def _invalidate_for(self, *relpaths):
        """Invalidates all files from the relpath, recursively up to the root.

        Many python operations implicitly create parent directories, so we assume that touching a
        file located below directories that do not currently exist will result in their creation.
        """
        files = {f for relpath in relpaths for f in recursive_dirname(relpath)}
        return self.scheduler.invalidate_files(files)

    def create_dir(self, relpath: str) -> str:
        """Creates a directory under the buildroot.

        :API: public

        relpath: The relative path to the directory from the build root.
        """
        path = os.path.join(self.build_root, relpath)
        safe_mkdir(path)
        self._invalidate_for(relpath)
        return path

    def create_file(self, relpath: str, contents: str = "", mode: str = "w") -> str:
        """Writes to a file under the buildroot.

        :API: public

        relpath:  The relative path to the file from the build root.
        contents: A string containing the contents of the file - '' by default..
        mode:     The mode to write to the file in - over-write by default.
        """
        path = os.path.join(self.build_root, relpath)
        with safe_open(path, mode=mode) as fp:
            fp.write(contents)
        self._invalidate_for(relpath)
        return path

    def create_files(self, path: str, files: Iterable[str]) -> None:
        """Writes to a file under the buildroot with contents same as file name.

        :API: public

         path:  The relative path to the file from the build root.
         files: List of file names.
        """
        for f in files:
            self.create_file(os.path.join(path, f), contents=f)

    def add_to_build_file(self, relpath: Union[str, PurePath], target: str) -> str:
        """Adds the given target specification to the BUILD file at relpath.

        :API: public

        relpath: The relative path to the BUILD file from the build root.
        target:  A string containing the target definition as it would appear in a BUILD file.
        """
        build_path = (
            relpath if PurePath(relpath).name.startswith("BUILD") else PurePath(relpath, "BUILD")
        )
        return self.create_file(str(build_path), target, mode="a")

    def make_snapshot(self, files: Dict[str, Union[str, bytes]]) -> Snapshot:
        """Makes a snapshot from a map of file name to file content."""
        with temporary_dir() as temp_dir:
            for file_name, content in files.items():
                mode = "wb" if isinstance(content, bytes) else "w"
                safe_file_dump(os.path.join(temp_dir, file_name), content, mode=mode)
            return cast(
                Snapshot,
                self.scheduler.capture_snapshots((PathGlobsAndRoot(PathGlobs(("**",)), temp_dir),))[
                    0
                ],
            )

    def make_snapshot_of_empty_files(self, files: Iterable[str]) -> Snapshot:
        """Makes a snapshot with empty content for each file.

        This is a convenience around `TestBase.make_snapshot`, which allows specifying the content
        for each file.
        """
        return self.make_snapshot({fp: "" for fp in files})
