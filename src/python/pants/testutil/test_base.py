# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import unittest
from abc import ABC, ABCMeta, abstractmethod
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import PurePath
from tempfile import mkdtemp
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    cast,
)

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
from pants.engine.process import InteractiveRunner
from pants.engine.rules import RootRule
from pants.engine.target import Target
from pants.init.engine_initializer import EngineInitializer
from pants.init.util import clean_global_runtime_state
from pants.option.global_options import ExecutionOptions, GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import GLOBAL_SCOPE
from pants.option.subsystem import Subsystem
from pants.source import source_root
from pants.testutil.engine_util import Params
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import (
    recursive_dirname,
    safe_file_dump,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
    safe_rmtree,
)
from pants.util.memo import memoized_method


class AbstractTestGenerator(ABC):
    """A mixin that facilitates test generation at runtime."""

    @classmethod
    @abstractmethod
    def generate_tests(cls):
        """Generate tests for a given class.

        This should be called against the composing class in its defining module, e.g.

          class ThingTest(TestGenerator):
            ...

          ThingTest.generate_tests()
        """

    @classmethod
    def add_test(cls, method_name, method):
        """A classmethod that adds dynamic test methods to a given class.

        :param string method_name: The name of the test method (e.g. `test_thing_x`).
        :param callable method: A callable representing the method. This should take a 'self' argument
                                as its first parameter for instance method binding.
        """
        assert not hasattr(
            cls, method_name
        ), f"a test with name `{method_name}` already exists on `{cls.__name__}`!"
        assert method_name.startswith("test_"), f"{method_name} is not a valid test name!"
        setattr(cls, method_name, method)


@dataclass(frozen=True)
class GoalRuleResult:
    exit_code: int
    stdout: str
    stderr: str

    @staticmethod
    def noop() -> "GoalRuleResult":
        return GoalRuleResult(0, stdout="", stderr="")


class TestBase(unittest.TestCase, metaclass=ABCMeta):
    """A baseclass useful for tests that run rules with a temporary build root.

    :API: public
    """

    additional_options: List[str] = []

    _scheduler: Optional[SchedulerSession] = None

    _P = TypeVar("_P")

    def request_product(
        self, product_type: Type["TestBase._P"], subjects: Iterable[Any]
    ) -> "TestBase._P":
        result = assert_single_element(
            self.scheduler.product_request(product_type, [Params(*subjects)])
        )
        return cast(TestBase._P, result)

    def run_goal_rule(
        self,
        goal: Type[Goal],
        *,
        global_args: Optional[Iterable[str]] = None,
        args: Optional[Iterable[str]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> GoalRuleResult:
        options_bootstrapper = create_options_bootstrapper(
            args=(*(global_args or []), goal.name, *(args or [])), env=env,
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

    def invalidate_for(self, *relpaths):
        """Invalidates all files from the relpath, recursively up to the root.

        Many python operations implicitly create parent directories, so we assume that touching a
        file located below directories that do not currently exist will result in their creation.
        """
        if self._scheduler is None:
            return
        files = {f for relpath in relpaths for f in recursive_dirname(relpath)}
        return self._scheduler.invalidate_files(files)

    def create_dir(self, relpath: str) -> str:
        """Creates a directory under the buildroot.

        :API: public

        relpath: The relative path to the directory from the build root.
        """
        path = os.path.join(self.build_root, relpath)
        safe_mkdir(path)
        self.invalidate_for(relpath)
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
        self.invalidate_for(relpath)
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

    @classmethod
    def alias_groups(cls):
        """
        :API: public
        """
        return BuildFileAliases()

    @classmethod
    def rules(cls):
        return [*source_root.rules(), RootRule(Address)]

    @classmethod
    def target_types(cls) -> Sequence[Type[Target]]:
        return ()

    @classmethod
    def build_config(cls):
        build_config = BuildConfiguration.Builder()
        build_config.register_aliases(cls.alias_groups())
        build_config.register_rules(cls.rules())
        build_config.register_target_types(cls.target_types())
        return build_config.create()

    def setUp(self):
        """
        :API: public
        """
        super().setUp()
        # Avoid resetting the Runtracker here, as that is specific to fork'd process cleanup.
        clean_global_runtime_state(reset_subsystem=True)

        self.addCleanup(self._reset_engine)

        safe_mkdir(self.build_root, clean=True)
        safe_mkdir(self.pants_workdir)
        self.addCleanup(safe_rmtree, self.build_root)

        BuildRoot().path = self.build_root
        self.addCleanup(BuildRoot().reset)

        self.subprocess_dir = os.path.join(self.build_root, ".pids")

        self.options = defaultdict(dict)  # scope -> key-value mapping.
        self.options[GLOBAL_SCOPE] = {
            "pants_workdir": self.pants_workdir,
            "pants_supportdir": os.path.join(self.build_root, "build-support"),
            "pants_distdir": os.path.join(self.build_root, "dist"),
            "pants_configdir": os.path.join(self.build_root, "config"),
            "pants_subprocessdir": self.subprocess_dir,
        }

        self._build_configuration = self.build_config()

    def _reset_engine(self):
        if self._scheduler is not None:
            self._scheduler.invalidate_all_files()

    @contextmanager
    def isolated_local_store(self):
        """Temporarily use an anonymous, empty Store for the Scheduler.

        In most cases we re-use a Store across all tests, since `file` and `directory` entries are
        content addressed, and `process` entries are intended to have strong cache keys. But when
        dealing with non-referentially transparent `process` executions, it can sometimes be
        necessary to avoid this cache.
        """
        self._scheduler = None
        local_store_dir = os.path.realpath(safe_mkdtemp())
        self._init_engine(local_store_dir=local_store_dir)
        try:
            yield
        finally:
            self._scheduler = None
            safe_rmtree(local_store_dir)

    @property
    def build_root(self) -> str:
        return self._build_root()

    @property
    def pants_workdir(self) -> str:
        return self._pants_workdir()

    @memoized_method
    def _build_root(self) -> str:
        return os.path.realpath(mkdtemp(suffix="_BUILD_ROOT"))

    @memoized_method
    def _pants_workdir(self) -> str:
        return os.path.join(self._build_root(), ".pants.d")

    def _init_engine(self, local_store_dir: Optional[str] = None) -> None:
        if self._scheduler is not None:
            return

        options_bootstrapper = OptionsBootstrapper.create(
            env={}, args=["--pants-config-files=[]", *self.additional_options], allow_pantsrc=False
        )
        global_options = options_bootstrapper.bootstrap_options.for_global_scope()
        local_store_dir = local_store_dir or global_options.local_store_dir
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
            build_configuration=self.build_config(),
            execution_options=ExecutionOptions.from_bootstrap_options(global_options),
        ).new_session(build_id="buildid_for_test", should_report_workunits=True)
        self._scheduler = graph_session.scheduler_session

    @property
    def scheduler(self) -> SchedulerSession:
        if self._scheduler is None:
            self._init_engine()
        return cast(SchedulerSession, self._scheduler)

    def tearDown(self):
        """
        :API: public
        """
        super().tearDown()
        Subsystem.reset()

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

    class _LoggingRecorder:
        """Simple logging handler to record warnings."""

        def __init__(self):
            self._records = []
            self.level = logging.DEBUG

        def handle(self, record):
            self._records.append(record)

        def _messages_for_level(self, levelname):
            return [
                f"{record.name}: {record.getMessage()}"
                for record in self._records
                if record.levelname == levelname
            ]

        def infos(self):
            return self._messages_for_level("INFO")

        def warnings(self):
            return self._messages_for_level("WARNING")

        def errors(self):
            return self._messages_for_level("ERROR")

    @contextmanager
    def captured_logging(self, level=None):
        root_logger = logging.getLogger()

        old_level = root_logger.level
        root_logger.setLevel(level or logging.NOTSET)

        handler = self._LoggingRecorder()
        root_logger.addHandler(handler)
        try:
            yield handler
        finally:
            root_logger.setLevel(old_level)
            root_logger.removeHandler(handler)
