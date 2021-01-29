# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import multiprocessing
import os
from dataclasses import dataclass
from io import StringIO
from pathlib import PurePath
from tempfile import mkdtemp
from types import CoroutineType, GeneratorType
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    cast,
)

from colors import blue, cyan, green, magenta, red, yellow

from pants.base.build_root import BuildRoot
from pants.base.specs_parser import SpecsParser
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.util_rules import pants_environment
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.fs import PathGlobs, PathGlobsAndRoot, Snapshot, Workspace
from pants.engine.goal import Goal
from pants.engine.internals.native import Native
from pants.engine.internals.native_engine import PyExecutor
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Get, Params
from pants.engine.internals.session import SessionValues
from pants.engine.process import InteractiveRunner
from pants.engine.rules import QueryRule as QueryRule
from pants.engine.rules import Rule
from pants.engine.target import Target, WrappedTarget
from pants.engine.unions import UnionMembership
from pants.init.engine_initializer import EngineInitializer
from pants.init.options_initializer import OptionsInitializer
from pants.option.global_options import ExecutionOptions, GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.source import source_root
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import (
    recursive_dirname,
    safe_file_dump,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
)
from pants.util.ordered_set import FrozenOrderedSet

# -----------------------------------------------------------------------------------------------
# `RuleRunner`
# -----------------------------------------------------------------------------------------------


_O = TypeVar("_O")


_EXECUTOR = PyExecutor(multiprocessing.cpu_count(), multiprocessing.cpu_count() * 4)


@dataclass(frozen=True)
class GoalRuleResult:
    exit_code: int
    stdout: str
    stderr: str

    @staticmethod
    def noop() -> GoalRuleResult:
        return GoalRuleResult(0, stdout="", stderr="")


# This is not frozen because we need to update the `scheduler` when setting options.
@dataclass
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
        isolated_local_store: bool = False,
        ca_certs_path: Optional[str] = None,
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
            *pants_environment.rules(),
            QueryRule(WrappedTarget, [Address]),
            QueryRule(UnionMembership, []),
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

        options_bootstrapper = create_options_bootstrapper()
        options = OptionsInitializer.create(options_bootstrapper, self.build_config)
        global_options = options_bootstrapper.bootstrap_options.for_global_scope()
        local_store_dir = (
            os.path.realpath(safe_mkdtemp())
            if isolated_local_store
            else global_options.local_store_dir
        )
        local_execution_root_dir = global_options.local_execution_root_dir
        named_caches_dir = global_options.named_caches_dir

        graph_session = EngineInitializer.setup_graph_extended(
            pants_ignore_patterns=OptionsInitializer.compute_pants_ignore(
                self.build_root, global_options
            ),
            use_gitignore=False,
            local_store_dir=local_store_dir,
            local_execution_root_dir=local_execution_root_dir,
            named_caches_dir=named_caches_dir,
            native=Native(),
            build_root=self.build_root,
            build_configuration=self.build_config,
            executor=_EXECUTOR,
            execution_options=ExecutionOptions.from_options(options),
            ca_certs_path=ca_certs_path,
            native_engine_visualize_to=None,
        ).new_session(
            build_id="buildid_for_test",
            session_values=SessionValues(
                {OptionsBootstrapper: options_bootstrapper, PantsEnvironment: PantsEnvironment()}
            ),
        )
        self.scheduler = graph_session.scheduler_session

    def __repr__(self) -> str:
        return f"RuleRunner(build_root={self.build_root})"

    @property
    def pants_workdir(self) -> str:
        return os.path.join(self.build_root, ".pants.d")

    @property
    def rules(self) -> FrozenOrderedSet[Rule]:
        return self.build_config.rules

    @property
    def target_types(self) -> FrozenOrderedSet[Type[Target]]:
        return self.build_config.target_types

    @property
    def union_membership(self) -> UnionMembership:
        """An instance of `UnionMembership` with all the test's registered `UnionRule`s."""
        return self.request(UnionMembership, [])

    def new_session(self, build_id: str) -> None:
        """Mutates this RuleRunner to begin a new Session with the same Scheduler."""
        self.scheduler = self.scheduler.scheduler.new_session(build_id)

    def request(self, output_type: Type[_O], inputs: Iterable[Any]) -> _O:
        result = assert_single_element(
            self.scheduler.product_request(output_type, [Params(*inputs)])
        )
        return cast(_O, result)

    def run_goal_rule(
        self,
        goal: Type[Goal],
        *,
        global_args: Optional[Iterable[str]] = None,
        args: Optional[Iterable[str]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> GoalRuleResult:
        merged_args = (*(global_args or []), goal.name, *(args or []))
        self.set_options(merged_args, env=env)
        options_bootstrapper = create_options_bootstrapper(args=merged_args, env=env)

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
                Workspace(self.scheduler),
                InteractiveRunner(self.scheduler),
            ),
        )

        console.flush()
        return GoalRuleResult(exit_code, stdout.getvalue(), stderr.getvalue())

    def set_options(self, args: Iterable[str], *, env: Optional[Mapping[str, str]] = None) -> None:
        """Update the engine session with new options and/or environment variables.

        The environment variables will be used to set the `PantsEnvironment`, which is the
        environment variables captured by the parent Pants process. Some rules use this to be able
        to read arbitrary env vars. Any options that start with `PANTS_` will also be used to set
        options.

        This will override any previously configured values.
        """
        options_bootstrapper = create_options_bootstrapper(args=args, env=env)
        self.scheduler = self.scheduler.scheduler.new_session(
            build_id="buildid_for_test",
            session_values=SessionValues(
                {OptionsBootstrapper: options_bootstrapper, PantsEnvironment: PantsEnvironment(env)}
            ),
        )

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

    def create_file(self, relpath: str, contents: Union[bytes, str] = "", mode: str = "w") -> str:
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

    def add_to_build_file(
        self, relpath: Union[str, PurePath], target: str, *, overwrite: bool = False
    ) -> str:
        """Adds the given target specification to the BUILD file at relpath.

        :API: public

        relpath: The relative path to the BUILD file from the build root.
        target:  A string containing the target definition as it would appear in a BUILD file.
        overwrite:  Whether to overwrite vs. append to the BUILD file.
        """
        build_path = (
            relpath if PurePath(relpath).name.startswith("BUILD") else PurePath(relpath, "BUILD")
        )
        mode = "w" if overwrite else "a"
        return self.create_file(str(build_path), target, mode=mode)

    def make_snapshot(self, files: Mapping[str, Union[str, bytes]]) -> Snapshot:
        """Makes a snapshot from a map of file name to file content."""
        with temporary_dir() as temp_dir:
            for file_name, content in files.items():
                mode = "wb" if isinstance(content, bytes) else "w"
                safe_file_dump(os.path.join(temp_dir, file_name), content, mode=mode)
            return self.scheduler.capture_snapshots(
                (PathGlobsAndRoot(PathGlobs(("**",)), temp_dir),)
            )[0]

    def make_snapshot_of_empty_files(self, files: Iterable[str]) -> Snapshot:
        """Makes a snapshot with empty content for each file.

        This is a convenience around `TestBase.make_snapshot`, which allows specifying the content
        for each file.
        """
        return self.make_snapshot({fp: "" for fp in files})

    def get_target(self, address: Address) -> Target:
        """Find the target for a given address.

        This requires that the target actually exists, i.e. that you called
        `rule_runner.add_to_build_file()`.
        """
        return self.request(WrappedTarget, [address]).target


# -----------------------------------------------------------------------------------------------
# `run_rule_with_mocks()`
# -----------------------------------------------------------------------------------------------


# TODO(#6742): Improve the type signature by using generics and type vars. `mock` should be
#  `Callable[[InputType], OutputType]`.
@dataclass(frozen=True)
class MockGet:
    output_type: Type
    input_type: Type
    mock: Callable[[Any], Any]


# TODO: Improve the type hints so that the return type can be inferred.
def run_rule_with_mocks(
    rule: Callable,
    *,
    rule_args: Optional[Sequence[Any]] = None,
    mock_gets: Optional[Sequence[MockGet]] = None,
    union_membership: Optional[UnionMembership] = None,
):
    """A test helper function that runs an @rule with a set of arguments and mocked Get providers.

    An @rule named `my_rule` that takes one argument and makes no `Get` requests can be invoked
    like so:

    ```
    return_value = run_rule_with_mocks(my_rule, rule_args=[arg1])
    ```

    In the case of an @rule that makes Get requests, things get more interesting: the
    `mock_gets` argument must be provided as a sequence of `MockGet`s. Each MockGet takes the Product
    and Subject type, along with a one-argument function that takes a subject value and returns a
    product value.

    So in the case of an @rule named `my_co_rule` that takes one argument and makes Get requests
    for a product type `Listing` with subject type `Dir`, the invoke might look like:

    ```
    return_value = run_rule_with_mocks(
      my_co_rule,
      rule_args=[arg1],
      mock_gets=[
        MockGet(
          output_type=Listing,
          input_type=Dir,
          mock=lambda dir_subject: Listing(..),
        ),
      ],
    )
    ```

    If any of the @rule's Get requests involve union members, you should pass a `UnionMembership`
    mapping the union base to any union members you'd like to test. For example, if your rule has
    `await Get(TestResult, TargetAdaptor, target_adaptor)`, you may pass
    `UnionMembership({TargetAdaptor: PythonTestsTargetAdaptor})` to this function.

    :returns: The return value of the completed @rule.
    """

    task_rule = getattr(rule, "rule", None)
    if task_rule is None:
        raise TypeError(f"Expected to receive a decorated `@rule`; got: {rule}")

    if rule_args is not None and len(rule_args) != len(task_rule.input_selectors):
        raise ValueError(
            f"Rule expected to receive arguments of the form: {task_rule.input_selectors}; got: {rule_args}"
        )

    if mock_gets is not None and len(mock_gets) != len(task_rule.input_gets):
        raise ValueError(
            f"Rule expected to receive Get providers for {task_rule.input_gets}; got: {mock_gets}"
        )

    res = rule(*(rule_args or ()))
    if not isinstance(res, (CoroutineType, GeneratorType)):
        return res

    def get(product, subject):
        provider = next(
            (
                mock_get.mock
                for mock_get in mock_gets
                if mock_get.output_type == product
                and (
                    mock_get.input_type == type(subject)
                    or (
                        union_membership
                        and union_membership.is_member(mock_get.input_type, subject)
                    )
                )
            ),
            None,
        )
        if provider is None:
            raise AssertionError(
                f"Rule requested: Get{(product, type(subject), subject)}, which cannot be satisfied."
            )
        return provider(subject)

    rule_coroutine = res
    rule_input = None
    while True:
        try:
            res = rule_coroutine.send(rule_input)
            if isinstance(res, Get):
                rule_input = get(res.output_type, res.input)
            elif type(res) in (tuple, list):
                rule_input = [get(g.output_type, g.input) for g in res]
            else:
                return res
        except StopIteration as e:
            if e.args:
                return e.value


class MockConsole:
    """An implementation of pants.engine.console.Console which captures output."""

    def __init__(self, use_colors=True):
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.use_colors = use_colors

    def write_stdout(self, payload):
        self.stdout.write(payload)

    def write_stderr(self, payload):
        self.stderr.write(payload)

    def print_stdout(self, payload):
        print(payload, file=self.stdout)

    def print_stderr(self, payload):
        print(payload, file=self.stderr)

    def _safe_color(self, text: str, color: Callable[[str], str]) -> str:
        return color(text) if self.use_colors else text

    def blue(self, text: str) -> str:
        return self._safe_color(text, blue)

    def cyan(self, text: str) -> str:
        return self._safe_color(text, cyan)

    def green(self, text: str) -> str:
        return self._safe_color(text, green)

    def magenta(self, text: str) -> str:
        return self._safe_color(text, magenta)

    def red(self, text: str) -> str:
        return self._safe_color(text, red)

    def yellow(self, text: str) -> str:
        return self._safe_color(text, yellow)
