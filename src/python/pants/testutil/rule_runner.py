# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import atexit
import dataclasses
import functools
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path, PurePath
from pprint import pformat
from tempfile import mkdtemp
from typing import (
    Any,
    Callable,
    Coroutine,
    Generator,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Type,
    TypeVar,
    cast,
    overload,
)

from pants.base.build_root import BuildRoot
from pants.base.specs_parser import SpecsParser
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.util_rules import adhoc_binaries
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, FileContent, Snapshot, Workspace
from pants.engine.goal import CurrentExecutingGoals, Goal
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import ProcessExecutionEnvironment, PyExecutor
from pants.engine.internals.scheduler import ExecutionError, Scheduler, SchedulerSession
from pants.engine.internals.selectors import Effect, Get, Params
from pants.engine.internals.session import SessionValues
from pants.engine.platform import Platform
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import QueryRule as QueryRule
from pants.engine.target import AllTargets, Target, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionMembership, UnionRule
from pants.init.engine_initializer import EngineInitializer
from pants.init.logging import initialize_stdio, initialize_stdio_raw, stdio_destination
from pants.option.global_options import (
    DynamicRemoteOptions,
    ExecutionOptions,
    GlobalOptions,
    LocalStoreOptions,
)
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.source import source_root
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.collections import assert_single_element
from pants.util.contextutil import pushd, temporary_dir, temporary_file
from pants.util.dirutil import recursive_dirname, safe_mkdir, safe_mkdtemp, safe_open
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


def logging(original_function=None, *, level: LogLevel = LogLevel.INFO):
    """A decorator that enables logging (optionally at the given level).

    May be used without a parameter list:

        ```
        @logging
        def test_function():
            ...
        ```

    ...or with a level argument:

        ```
        @logging(level=LogLevel.DEBUG)
        def test_function():
            ...
        ```
    """

    def _decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            stdout_fileno, stderr_fileno = sys.stdout.fileno(), sys.stderr.fileno()
            with temporary_dir() as tempdir, initialize_stdio_raw(
                level, False, False, {}, True, [], tempdir
            ), stdin_context() as stdin, stdio_destination(
                stdin.fileno(), stdout_fileno, stderr_fileno
            ):
                return func(*args, **kwargs)

        return wrapper

    if original_function:
        return _decorate(original_function)
    return _decorate


@contextmanager
def engine_error(
    expected_underlying_exception: type[Exception] = Exception,
    *,
    contains: str | None = None,
    normalize_tracebacks: bool = False,
) -> Iterator[None]:
    """A context manager to catch `ExecutionError`s in tests and check that the underlying exception
    is expected.

    Use like this:

        with engine_error(ValueError, contains="foo"):
            rule_runner.request(OutputType, [input])

    Will raise AssertionError if no ExecutionError occurred.

    Set `normalize_tracebacks=True` to replace file locations and addresses in the error message
    with fixed values for testability, and check `contains` against the `ExecutionError` message
    instead of the underlying error only.
    """
    try:
        yield
    except ExecutionError as exec_error:
        if not len(exec_error.wrapped_exceptions) == 1:
            formatted_errors = "\n\n".join(repr(e) for e in exec_error.wrapped_exceptions)
            raise ValueError(
                softwrap(
                    f"""
                    Multiple underlying exceptions, but this helper function expected only one.
                    Use `with pytest.raises(ExecutionError) as exc` directly and inspect
                    `exc.value.wrapped_exceptions`.

                    Errors: {formatted_errors}
                    """
                )
            )
        underlying = exec_error.wrapped_exceptions[0]
        if not isinstance(underlying, expected_underlying_exception):
            raise AssertionError(
                softwrap(
                    f"""
                    ExecutionError occurred as expected, but the underlying exception had type
                    {type(underlying)} rather than the expected type
                    {expected_underlying_exception}:

                    {underlying}
                    """
                )
            )
        if contains is not None:
            if normalize_tracebacks:
                errmsg = remove_locations_from_traceback(str(exec_error))
            else:
                errmsg = str(underlying)
            if contains not in errmsg:
                raise AssertionError(
                    softwrap(
                        f"""
                        Expected value not found in exception.

                        => Expected: {contains}

                        => Actual: {errmsg}
                        """
                    )
                )
    else:
        raise AssertionError(
            softwrap(
                f"""
                DID NOT RAISE ExecutionError with underlying exception type
                {expected_underlying_exception}.
                """
            )
        )


def remove_locations_from_traceback(trace: str) -> str:
    location_pattern = re.compile(r'"/.*", line \d+')
    address_pattern = re.compile(r"0x[0-9a-f]+")
    new_trace = location_pattern.sub("LOCATION-INFO", trace)
    new_trace = address_pattern.sub("0xEEEEEEEEE", new_trace)
    return new_trace


# -----------------------------------------------------------------------------------------------
# `RuleRunner`
# -----------------------------------------------------------------------------------------------


_I = TypeVar("_I")
_O = TypeVar("_O")


# A global executor for Schedulers created in unit tests, which is shutdown using `atexit`. This
# allows for reusing threads, and avoids waiting for straggling tasks during teardown of each test.
EXECUTOR = PyExecutor(
    # Use the ~minimum possible parallelism since integration tests using RuleRunner will already
    # be run by Pants using an appropriate Parallelism. We must set max_threads > core_threads; so
    # 2 is the minimum, but, via trial and error, 3 minimizes test times on average.
    core_threads=1,
    max_threads=3,
)
atexit.register(lambda: EXECUTOR.shutdown(5))


# Environment variable names required for locating Python interpreters, for use with RuleRunner's
# env_inherit arguments.
# TODO: This is verbose and redundant: see https://github.com/pantsbuild/pants/issues/13350.
PYTHON_BOOTSTRAP_ENV = {"PATH", "PYENV_ROOT", "HOME"}


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
    options_bootstrapper: OptionsBootstrapper
    extra_session_values: dict[Any, Any]
    max_workunit_verbosity: LogLevel
    build_config: BuildConfiguration
    scheduler: SchedulerSession
    rules: tuple[Any, ...]

    def __init__(
        self,
        *,
        rules: Iterable | None = None,
        target_types: Iterable[type[Target]] | None = None,
        objects: dict[str, Any] | None = None,
        aliases: Iterable[BuildFileAliases] | None = None,
        context_aware_object_factories: dict[str, Any] | None = None,
        isolated_local_store: bool = False,
        preserve_tmpdirs: bool = False,
        ca_certs_path: str | None = None,
        bootstrap_args: Iterable[str] = (),
        extra_session_values: dict[Any, Any] | None = None,
        max_workunit_verbosity: LogLevel = LogLevel.DEBUG,
        inherent_environment: EnvironmentName | None = EnvironmentName(None),
        is_bootstrap: bool = False,
    ) -> None:
        bootstrap_args = [*bootstrap_args]

        root_dir: Path | None = None
        if preserve_tmpdirs:
            root_dir = Path(mkdtemp(prefix="RuleRunner."))
            print(f"Preserving rule runner temporary directories at {root_dir}.", file=sys.stderr)
            bootstrap_args.extend(
                ["--keep-sandboxes=always", f"--local-execution-root-dir={root_dir}"]
            )
            build_root = (root_dir / "BUILD_ROOT").resolve()
            build_root.mkdir()
            self.build_root = str(build_root)
        else:
            self.build_root = os.path.realpath(safe_mkdtemp(prefix="_BUILD_ROOT"))

        safe_mkdir(self.pants_workdir)
        BuildRoot().path = self.build_root

        def rewrite_rule_for_inherent_environment(rule):
            if not inherent_environment or not isinstance(rule, QueryRule):
                return rule
            return QueryRule(rule.output_type, OrderedSet((*rule.input_types, EnvironmentName)))

        # TODO: Redesign rule registration for tests to be more ergonomic and to make this less
        #  special-cased.
        self.rules = tuple(rewrite_rule_for_inherent_environment(rule) for rule in (rules or ()))
        all_rules = (
            *self.rules,
            *source_root.rules(),
            *adhoc_binaries.rules(),
            QueryRule(WrappedTarget, [WrappedTargetRequest]),
            QueryRule(AllTargets, []),
            QueryRule(UnionMembership, []),
        )
        build_config_builder = BuildConfiguration.Builder()
        build_config_builder.register_aliases(
            BuildFileAliases(
                objects=objects, context_aware_object_factories=context_aware_object_factories
            )
        )
        aliases = aliases or ()
        for build_file_aliases in aliases:
            build_config_builder.register_aliases(build_file_aliases)

        build_config_builder.register_rules("_dummy_for_test_", all_rules)
        build_config_builder.register_target_types("_dummy_for_test_", target_types or ())
        self.build_config = build_config_builder.create()

        self.environment = CompleteEnvironmentVars({})
        self.options_bootstrapper = self.create_options_bootstrapper(args=bootstrap_args, env=None)
        self.extra_session_values = extra_session_values or {}
        self.inherent_environment = inherent_environment
        self.max_workunit_verbosity = max_workunit_verbosity
        options = self.options_bootstrapper.full_options(
            self.build_config,
            union_membership=UnionMembership.from_rules(
                rule for rule in self.rules if isinstance(rule, UnionRule)
            ),
        )
        global_options = self.options_bootstrapper.bootstrap_options.for_global_scope()

        dynamic_remote_options, _ = DynamicRemoteOptions.from_options(options, self.environment)
        local_store_options = LocalStoreOptions.from_options(global_options)
        if isolated_local_store:
            if root_dir:
                lmdb_store_dir = root_dir / "lmdb_store"
                lmdb_store_dir.mkdir()
                store_dir = str(lmdb_store_dir)
            else:
                store_dir = safe_mkdtemp(prefix="lmdb_store.")
            local_store_options = dataclasses.replace(local_store_options, store_dir=store_dir)

        local_execution_root_dir = global_options.local_execution_root_dir
        named_caches_dir = global_options.named_caches_dir

        self._set_new_session(
            EngineInitializer.setup_graph_extended(
                pants_ignore_patterns=GlobalOptions.compute_pants_ignore(
                    self.build_root, global_options
                ),
                use_gitignore=False,
                local_store_options=local_store_options,
                local_execution_root_dir=local_execution_root_dir,
                named_caches_dir=named_caches_dir,
                build_root=self.build_root,
                build_configuration=self.build_config,
                # Each Scheduler that is created borrows the global executor, which is shut down `atexit`.
                executor=EXECUTOR.to_borrowed(),
                execution_options=ExecutionOptions.from_options(
                    global_options, dynamic_remote_options
                ),
                ca_certs_path=ca_certs_path,
                engine_visualize_to=None,
                is_bootstrap=is_bootstrap,
            ).scheduler
        )

    def __repr__(self) -> str:
        return f"RuleRunner(build_root={self.build_root})"

    def _set_new_session(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler.new_session(
            build_id="buildid_for_test",
            session_values=SessionValues(
                {
                    OptionsBootstrapper: self.options_bootstrapper,
                    CompleteEnvironmentVars: self.environment,
                    CurrentExecutingGoals: CurrentExecutingGoals(),
                    **self.extra_session_values,
                }
            ),
            max_workunit_level=self.max_workunit_verbosity,
        )

    @property
    def pants_workdir(self) -> str:
        return os.path.join(self.build_root, ".pants.d", "workdir")

    @property
    def target_types(self) -> tuple[type[Target], ...]:
        return self.build_config.target_types

    @property
    def union_membership(self) -> UnionMembership:
        """An instance of `UnionMembership` with all the test's registered `UnionRule`s."""
        return self.request(UnionMembership, [])

    def new_session(self, build_id: str) -> None:
        """Mutates this RuleRunner to begin a new Session with the same Scheduler."""
        self.scheduler = self.scheduler.scheduler.new_session(build_id)

    def request(self, output_type: type[_O], inputs: Iterable[Any]) -> _O:
        params = (
            Params(*inputs, self.inherent_environment)
            if self.inherent_environment
            else Params(*inputs)
        )
        result = assert_single_element(self.scheduler.product_request(output_type, [params]))
        return cast(_O, result)

    def run_goal_rule(
        self,
        goal: type[Goal],
        *,
        global_args: Iterable[str] | None = None,
        args: Iterable[str] | None = None,
        env: Mapping[str, str] | None = None,
        env_inherit: set[str] | None = None,
    ) -> GoalRuleResult:
        merged_args = (*(global_args or []), goal.name, *(args or []))
        self.set_options(merged_args, env=env, env_inherit=env_inherit)

        raw_specs = self.options_bootstrapper.full_options_for_scopes(
            [GlobalOptions.get_scope_info(), goal.subsystem_cls.get_scope_info()],
            self.union_membership,
        ).specs
        specs = SpecsParser(root_dir=self.build_root).parse_specs(
            raw_specs, description_of_origin="RuleRunner.run_goal_rule()"
        )

        stdout, stderr = StringIO(), StringIO()
        console = Console(stdout=stdout, stderr=stderr, use_colors=False, session=self.scheduler)

        exit_code = self.scheduler.run_goal_rule(
            goal,
            Params(
                specs,
                console,
                Workspace(self.scheduler),
                *([self.inherent_environment] if self.inherent_environment else []),
            ),
        )

        console.flush()
        return GoalRuleResult(exit_code, stdout.getvalue(), stderr.getvalue())

    def create_options_bootstrapper(
        self, args: Iterable[str], env: Mapping[str, str] | None
    ) -> OptionsBootstrapper:
        return create_options_bootstrapper(args=args, env=env)

    def set_options(
        self,
        args: Iterable[str],
        *,
        env: Mapping[str, str] | None = None,
        env_inherit: set[str] | None = None,
    ) -> None:
        """Update the engine session with new options and/or environment variables.

        The environment variables will be used to set the `CompleteEnvironmentVars`, which is the
        environment variables captured by the parent Pants process. Some rules use this to be able
        to read arbitrary env vars. Any options that start with `PANTS_` will also be used to set
        options.

        Environment variables listed in `env_inherit` and not in `env` will be inherited from the test
        runner's environment (os.environ)

        This will override any previously configured values.
        """
        env = {
            **{k: os.environ[k] for k in (env_inherit or set()) if k in os.environ},
            **(env or {}),
        }
        self.options_bootstrapper = self.create_options_bootstrapper(args=args, env=env)
        self.environment = CompleteEnvironmentVars(env)
        self._set_new_session(self.scheduler.scheduler)

    def set_session_values(
        self,
        extra_session_values: dict[Any, Any],
    ) -> None:
        """Update the engine Session with new session_values."""
        self.extra_session_values = extra_session_values
        self._set_new_session(self.scheduler.scheduler)

    def _invalidate_for(self, *relpaths: str):
        """Invalidates all files from the relpath, recursively up to the root.

        Many python operations implicitly create parent directories, so we assume that touching a
        file located below directories that do not currently exist will result in their creation.
        """
        files = {f for relpath in relpaths for f in recursive_dirname(relpath)}
        return self.scheduler.invalidate_files(files)

    def chmod(self, relpath: str | PurePath, mode: int) -> None:
        """Change the file mode and permissions.

        relpath: The relative path to the file or directory from the build root.
        mode: The file mode to set, preferable in octal representation, e.g. `mode=0o750`.
        """
        Path(self.build_root, relpath).chmod(mode)
        self._invalidate_for(str(relpath))

    def create_dir(self, relpath: str) -> str:
        """Creates a directory under the buildroot.

        :API: public

        relpath: The relative path to the directory from the build root.
        """
        path = os.path.join(self.build_root, relpath)
        safe_mkdir(path)
        self._invalidate_for(relpath)
        return path

    def _create_file(
        self, relpath: str | PurePath, contents: bytes | str = "", mode: str = "w"
    ) -> str:
        """Writes to a file under the buildroot.

        relpath: The relative path to the file from the build root.
        contents: A string containing the contents of the file - '' by default..
        mode: The mode to write to the file in - over-write by default.
        """
        path = os.path.join(self.build_root, relpath)
        with safe_open(path, mode=mode) as fp:
            fp.write(contents)
        self._invalidate_for(str(relpath))
        return path

    @overload
    def write_files(self, files: Mapping[str, str | bytes]) -> tuple[str, ...]:
        ...

    @overload
    def write_files(self, files: Mapping[PurePath, str | bytes]) -> tuple[str, ...]:
        ...

    def write_files(
        self, files: Mapping[PurePath, str | bytes] | Mapping[str, str | bytes]
    ) -> tuple[str, ...]:
        """Write the files to the build root.

        :API: public

        files: A mapping of file names to contents.
        returns: A tuple of absolute file paths created.
        """
        paths = []
        for path, content in files.items():
            paths.append(
                self._create_file(path, content, mode="wb" if isinstance(content, bytes) else "w")
            )
        return tuple(paths)

    def read_file(self, file: str | PurePath, mode: str = "r") -> str | bytes:
        """Read a file that was written to the build root, useful for testing."""
        path = os.path.join(self.build_root, file)
        with safe_open(path, mode=mode) as fp:
            if "b" in mode:
                return bytes(fp.read())
            return str(fp.read())

    def make_snapshot(self, files: Mapping[str, str | bytes]) -> Snapshot:
        """Makes a snapshot from a map of file name to file content.

        :API: public
        """
        file_contents = [
            FileContent(path, content.encode() if isinstance(content, str) else content)
            for path, content in files.items()
        ]
        digest = self.request(Digest, [CreateDigest(file_contents)])
        return self.request(Snapshot, [digest])

    def make_snapshot_of_empty_files(self, files: Iterable[str]) -> Snapshot:
        """Makes a snapshot with empty content for each file.

        This is a convenience around `TestBase.make_snapshot`, which allows specifying the content
        for each file.

        :API: public
        """
        return self.make_snapshot({fp: "" for fp in files})

    def get_target(self, address: Address) -> Target:
        """Find the target for a given address.

        This requires that the target actually exists, i.e. that you set up its BUILD file.

        :API: public
        """
        return self.request(
            WrappedTarget,
            [WrappedTargetRequest(address, description_of_origin="RuleRunner.get_target()")],
        ).target

    def write_digest(
        self, digest: Digest, *, path_prefix: str | None = None, clear_paths: Sequence[str] = ()
    ) -> None:
        """Write a digest to disk, relative to the test's build root.

        Access the written files by using `os.path.join(rule_runner.build_root, <relpath>)`.
        """
        native_engine.write_digest(
            self.scheduler.py_scheduler,
            self.scheduler.py_session,
            digest,
            path_prefix or "",
            clear_paths,
        )

    def run_interactive_process(self, request: InteractiveProcess) -> InteractiveProcessResult:
        with pushd(self.build_root):
            return native_engine.session_run_interactive_process(
                self.scheduler.py_session,
                request,
                ProcessExecutionEnvironment(
                    environment_name=None,
                    platform=Platform.create_for_localhost().value,
                    docker_image=None,
                    remote_execution=False,
                    remote_execution_extra_platform_properties=[],
                    execute_in_workspace=False,
                ),
            )

    def do_not_use_mock(self, output_type: Type, input_types: Iterable[type]) -> MockGet:
        """Returns a `MockGet` whose behavior is to run the actual rule using this `RuleRunner`"""
        return MockGet(
            output_type=output_type,
            input_types=tuple(input_types),
            mock=lambda *input_values: self.request(output_type, input_values),
        )


# -----------------------------------------------------------------------------------------------
# `run_rule_with_mocks()`
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MockEffect(Generic[_O]):
    output_type: type[_O]
    input_types: tuple[type, ...]
    mock: Callable[..., _O]


@dataclass(frozen=True)
class MockGet(Generic[_O]):
    output_type: type[_O]
    input_types: tuple[type, ...]
    mock: Callable[..., _O]


def run_rule_with_mocks(
    rule: Callable[..., Coroutine[Any, Any, _O]],
    *,
    rule_args: Sequence[Any] = (),
    mock_gets: Sequence[MockGet | MockEffect] = (),
    union_membership: UnionMembership | None = None,
) -> _O:
    """A test helper function that runs an @rule with a set of arguments and mocked Get providers.

    An @rule named `my_rule` that takes one argument and makes no `Get` requests can be invoked
    like so:

    ```
    return_value = run_rule_with_mocks(my_rule, rule_args=[arg1])
    ```

    In the case of an @rule that makes Get requests, things get more interesting: the
    `mock_gets` argument must be provided as a sequence of `MockGet`s and `MockEffect`s. Each
    MockGet takes the Product and Subject type, along with a one-argument function that takes a
    subject value and returns a product value.

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

    func: Callable[..., Coroutine[Any, Any, _O]] | Callable[..., _O]

    # Perform additional validation on `@rule` that the correct args are provided. We don't have
    # an easy way to do this for async helper calls yet.
    if task_rule:
        if len(rule_args) != len(task_rule.parameters):
            raise ValueError(
                f"Rule expected to receive arguments of the form: {task_rule.parameters}; got: {rule_args}"
            )

        if len(mock_gets) != len(task_rule.awaitables):
            raise ValueError(
                f"Rule expected to receive Get providers for:\n"
                f"{pformat(task_rule.awaitables)}\ngot:\n"
                f"{pformat(mock_gets)}"
            )
        # Access the original function, rather than the trampoline that we would get by calling
        # it directly.
        func = task_rule.func
    else:
        func = rule

    res = func(*(rule_args or ()))
    if not isinstance(res, (Coroutine, Generator)):
        return res

    def get(res: Get | Effect):
        provider = next(
            (
                mock_get.mock
                for mock_get in mock_gets
                if mock_get.output_type == res.output_type
                and all(
                    type(val) in mock_get.input_types
                    or (
                        union_membership
                        and any(
                            input_type in union_membership
                            and union_membership.is_member(input_type, val)
                            for input_type in mock_get.input_types
                        )
                    )
                    for val in res.inputs
                )
            ),
            None,
        )
        if provider is None:
            raise AssertionError(f"Rule requested: {res}, which cannot be satisfied.")
        return provider(*res.inputs)

    rule_coroutine = res
    rule_input = None
    while True:
        try:
            res = rule_coroutine.send(rule_input)
            if isinstance(res, (Get, Effect)):
                rule_input = get(res)
            elif type(res) in (tuple, list):
                rule_input = [get(g) for g in res]  # type: ignore[union-attr]
            else:
                return res  # type: ignore[return-value]
        except StopIteration as e:
            return e.value  # type: ignore[no-any-return]


@contextmanager
def stdin_context(content: bytes | str | None = None):
    if content is None:
        yield open("/dev/null")
    else:
        with temporary_file(binary_mode=isinstance(content, bytes)) as stdin_file:
            stdin_file.write(content)
            stdin_file.close()
            yield open(stdin_file.name)


@contextmanager
def mock_console(
    options_bootstrapper: OptionsBootstrapper,
    *,
    stdin_content: bytes | str | None = None,
) -> Iterator[tuple[Console, StdioReader]]:
    global_bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
    colors = (
        options_bootstrapper.full_options_for_scopes(
            [GlobalOptions.get_scope_info()], UnionMembership({}), allow_unknown_options=True
        )
        .for_global_scope()
        .colors
    )

    with initialize_stdio(global_bootstrap_options), stdin_context(
        stdin_content
    ) as stdin, temporary_file(binary_mode=False) as stdout, temporary_file(
        binary_mode=False
    ) as stderr, stdio_destination(
        stdin_fileno=stdin.fileno(),
        stdout_fileno=stdout.fileno(),
        stderr_fileno=stderr.fileno(),
    ):
        # NB: We yield a Console without overriding the destination argument, because we have
        # already done a sys.std* level replacement. The replacement is necessary in order for
        # InteractiveProcess to have native file handles to interact with.
        yield Console(use_colors=colors), StdioReader(
            _stdout=Path(stdout.name), _stderr=Path(stderr.name)
        )


@dataclass
class StdioReader:
    _stdout: Path
    _stderr: Path

    def get_stdout(self) -> str:
        """Return all data that has been flushed to stdout so far."""
        return self._stdout.read_text()

    def get_stderr(self) -> str:
        """Return all data that has been flushed to stderr so far."""
        return self._stderr.read_text()
