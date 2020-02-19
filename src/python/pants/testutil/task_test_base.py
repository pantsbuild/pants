# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import subprocess
from abc import abstractmethod
from contextlib import closing, contextmanager
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Tuple

from pants.goal.goal import Goal
from pants.ivy.bootstrapper import Bootstrapper
from pants.task.console_task import ConsoleTask
from pants.task.task import Task
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_method
from pants.util.meta import classproperty


# TODO: Find a better home for this?
def is_exe(name):
    result = subprocess.call(
        ["which", name], stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT
    )
    return result == 0


def ensure_cached(task_cls, expected_num_artifacts=None):
    """Decorator for a task-executing unit test. Asserts that after running the decorated test
    function, the cache for task_cls contains expected_num_artifacts.

    Uses a new temp dir for the artifact cache, and uses a glob based on the
    task's synthesized subtype to find the cache directories within the new temp
    dir which were generated by the actions performed within the test method.

    :API: public

    :param task_cls: Class of the task to check the artifact cache
                     for (e.g. JarCreate).
    :param expected_num_artifacts: Expected number of artifacts to be in the
                                   task's cache after running the test. If
                                   unspecified, will assert that the number of
                                   artifacts in the cache is non-zero.
    """

    def decorator(test_fn):
        def wrapper(self, *args, **kwargs):
            with self.cache_check(expected_num_artifacts=expected_num_artifacts):
                test_fn(self, *args, **kwargs)

        return wrapper

    return decorator


class TaskTestBase(TestBase):
    """A baseclass useful for testing a single Task type.

    :API: public
    """

    options_scope = "test_scope"

    @classmethod
    @abstractmethod
    def task_type(cls):
        """Subclasses must return the type of the Task subclass under test.

        :API: public
        """

    def setUp(self):
        """
    :API: public
    """
        super().setUp()
        self._testing_task_type = self.synthesize_task_subtype(self.task_type(), self.options_scope)
        # We locate the workdir below the pants_workdir, which BaseTest locates within the BuildRoot.
        # BaseTest cleans this up, so we don't need to.  We give it a stable name, so that we can
        # use artifact caching to speed up tests.
        self._test_workdir = os.path.join(self.pants_workdir, self.task_type().stable_name())
        os.mkdir(self._test_workdir)
        # TODO: Push this down to JVM-related tests only? Seems wrong to have an ivy-specific
        # action in this non-JVM-specific, high-level base class.
        Bootstrapper.reset_instance()

    @property
    def test_workdir(self):
        """
    :API: public
    """
        return self._test_workdir

    def synthesize_task_subtype(self, task_type, options_scope):
        """Creates a synthetic subclass of the task type.

        Note that passing in a stable options scope will speed up some tests, as the scope may appear
        in the paths of tools used by the task, and if these are stable, tests can get artifact
        cache hits when bootstrapping these tools. This doesn't hurt test isolation, as we reset
        class-level state between each test.

        # TODO: Use the task type directly once we re-do the Task lifecycle.

        :API: public

        :param task_type: The task type to subtype.
        :param options_scope: The scope to give options on the generated task type.
        :return: A pair (type, options_scope)
        """
        subclass_name = f"test_{task_type.__name__}_{options_scope}"
        return type(
            subclass_name,
            (task_type,),
            {"_stable_name": task_type._compute_stable_name(), "options_scope": options_scope},
        )

    def set_options(self, **kwargs):
        """
    :API: public
    """
        self.set_options_for_scope(self.options_scope, **kwargs)

    def context(self, for_task_types=None, **kwargs):
        """
    :API: public
    """
        # Add in our task type.
        for_task_types = [self._testing_task_type] + (for_task_types or [])
        return super().context(for_task_types=for_task_types, **kwargs)

    def create_task(self, context, workdir=None):
        """
    :API: public
    """
        if workdir is None:
            workdir = self.test_workdir
        return self._testing_task_type(context, workdir)

    @contextmanager
    def cache_check(self, expected_num_artifacts=None):
        """Sets up a temporary artifact cache and checks that the yielded-to code populates it.

        :param expected_num_artifacts: Expected number of artifacts to be in the cache after yielding.
                                       If unspecified, will assert that the number of artifacts in the
                                       cache is non-zero.
        """
        with temporary_dir() as artifact_cache:
            self.set_options_for_scope(f"cache.{self.options_scope}", write_to=[artifact_cache])

            yield

            cache_subdir_glob_str = os.path.join(artifact_cache, "*/")
            cache_subdirs = glob.glob(cache_subdir_glob_str)

            if expected_num_artifacts == 0:
                self.assertEqual(len(cache_subdirs), 0)
                return

            self.assertEqual(len(cache_subdirs), 1)
            task_cache = cache_subdirs[0]

            num_artifacts = 0
            for (_, _, files) in os.walk(task_cache):
                num_artifacts += len(files)

            if expected_num_artifacts is None:
                self.assertNotEqual(num_artifacts, 0)
            else:
                self.assertEqual(num_artifacts, expected_num_artifacts)

    def make_linear_graph(self, names, **additional_target_args):
        # A build graph where a -(depends on)-> b -> ... -> e
        graph = {}
        last_target = None
        for name in reversed(names):
            last_target = self.make_target(
                f"project_info:{name}",
                dependencies=[] if last_target is None else [last_target],
                **additional_target_args,
            )
            graph[name] = last_target
        return graph


class ConsoleTaskTestBase(TaskTestBase):
    """A base class useful for testing ConsoleTasks.

    :API: public
    """

    def setUp(self):
        """
    :API: public
    """
        Goal.clear()
        super().setUp()

        task_type = self.task_type()
        assert issubclass(
            task_type, ConsoleTask
        ), f"task_type() must return a ConsoleTask subclass, got {task_type}"

    def execute_task(self, targets=None, options=None):
        """Creates a new task and executes it with the given config, command line args and targets.

        :API: public

        :param targets: Optional list of Target objects passed on the command line.
        Returns the text output of the task.
        """
        options = options or {}
        with closing(BytesIO()) as output:
            self.set_options(**options)
            context = self.context(target_roots=targets, console_outstream=output)
            task = self.create_task(context)
            task.execute()
            return output.getvalue().decode()

    def execute_console_task(
        self,
        targets=None,
        extra_targets=None,
        options=None,
        passthru_args=None,
        workspace=None,
        scheduler=None,
    ):
        """Creates a new task and executes it with the given config, command line args and targets.

        :API: public

        :param options: option values.
        :param targets: optional list of Target objects passed on the command line.
        :param extra_targets: optional list of extra targets in the context in addition to those
                              passed on the command line.
        :param passthru_args: optional list of passthru_args
        :param workspace: optional Workspace to pass into the context.

        Returns the list of items returned from invoking the console task's console_output method.
        """
        options = options or {}
        self.set_options(**options)
        context = self.context(
            target_roots=targets,
            passthru_args=passthru_args,
            workspace=workspace,
            scheduler=scheduler,
        )
        return self.execute_console_task_given_context(context, extra_targets=extra_targets)

    def execute_console_task_given_context(self, context, extra_targets=None):
        """Creates a new task and executes it with the context and extra targets.

        :API: public

        :param context: The pants run context to use.
        :param extra_targets: An optional list of extra targets in the context in addition to those
                              passed on the command line.
        :returns: The list of items returned from invoking the console task's console_output method.
        :rtype: list of strings
        """
        task = self.create_task(context)
        input_targets = task.get_targets() if task.act_transitively else context.target_roots
        return list(task.console_output(list(input_targets) + list(extra_targets or ())))

    def assert_entries(self, sep, *output, **kwargs):
        """Verifies the expected output text is flushed by the console task under test.

        NB: order of entries is not tested, just presence.

        :API: public

        sep:      the expected output separator.
        *output:  the output entries expected between the separators
        **options: additional options passed to execute_task.
        """
        # We expect each output line to be suffixed with the separator, so for , and [1,2,3] we expect:
        # '1,2,3,' - splitting this by the separator we should get ['1', '2', '3', ''] - always an extra
        # empty string if the separator is properly always a suffix and not applied just between
        # entries.
        self.assertEqual(
            sorted(list(output) + [""]), sorted((self.execute_task(**kwargs)).split(sep))
        )

    def assert_console_output(self, *output, **kwargs):
        """Verifies the expected output entries are emitted by the console task under test.

        NB: order of entries is not tested, just presence.

        :API: public

        *output:  the expected output entries
        **kwargs: additional kwargs passed to execute_console_task.
        """
        self.assertEqual(sorted(output), sorted(self.execute_console_task(**kwargs)))

    def assert_console_output_contains(self, output, **kwargs):
        """Verifies the expected output string is emitted by the console task under test.

        :API: public

        output:  the expected output entry(ies)
        **kwargs: additional kwargs passed to execute_console_task.
        """
        self.assertIn(output, self.execute_console_task(**kwargs))

    def assert_console_output_ordered(self, *output, **kwargs):
        """Verifies the expected output entries are emitted by the console task under test.

        NB: order of entries is tested.

        :API: public

        *output:  the expected output entries in expected order
        **kwargs: additional kwargs passed to execute_console_task.
        """
        self.assertEqual(list(output), self.execute_console_task(**kwargs))

    def assert_console_raises(self, exception, **kwargs):
        """Verifies the expected exception is raised by the console task under test.

        :API: public

        **kwargs: additional kwargs are passed to execute_console_task.
        """
        with self.assertRaises(exception):
            self.execute_console_task(**kwargs)


class DeclarativeTaskTestMixin:
    """Experimental mixin for task tests allows specifying tasks to be run before or after the task.

    Calling `self.invoke_tasks()` will create instances of and execute task types in
    `self.run_before_task_types()`, then `task_type()`, then `self.run_after_task_types()`.
    """

    @classproperty
    def run_before_task_types(cls):
        return []

    @classproperty
    def run_after_task_types(cls):
        return []

    @memoized_method
    def _synthesize_task_types(self, task_types=()):
        return [
            self.synthesize_task_subtype(tsk, f"__tmp_{tsk.__name__}")
            # TODO(#7127): make @memoized_method convert lists to tuples for hashing!
            for tsk in task_types
        ]

    def _create_task(self, task_type, context):
        """Helper method to instantiate tasks besides self._testing_task_type in the test
        workdir."""
        return task_type(context, self.test_workdir)

    @dataclass(frozen=True)
    class TaskInvocationResult:
        context: Any
        before_tasks: Tuple[Task, ...]
        this_task: Task
        after_tasks: Tuple[Task, ...]

    def invoke_tasks(self, target_closure=None, **context_kwargs):
        """Create and execute the declaratively specified tasks in order.

        Create instances of and execute task types in `self.run_before_task_types()`, then
        `task_type()`, then `self.run_after_task_types()`.

        :param Iterable target_closure: If not None, check that the build graph contains exactly these
                                        targets before executing the tasks.
        :param **context_kwargs: kwargs passed to `self.context()`. Note that this method already sets
                                        `for_task_types`.
        :return: A datatype containing the created context and the task instances which were executed.
        :raises: If any exception is raised during task execution, the context will be attached to the
                 exception object as the attribute '_context' with setattr() before re-raising.
        """
        run_before_synthesized_task_types = self._synthesize_task_types(
            tuple(self.run_before_task_types)
        )
        run_after_synthesized_task_types = self._synthesize_task_types(
            tuple(self.run_after_task_types)
        )
        all_synthesized_task_types = (
            run_before_synthesized_task_types
            + [self._testing_task_type,]
            + run_after_synthesized_task_types
        )

        context = self.context(for_task_types=all_synthesized_task_types, **context_kwargs)
        if target_closure is not None:
            assert set(target_closure) == set(context.build_graph.targets())

        run_before_task_instances = [
            self._create_task(task_type, context) for task_type in run_before_synthesized_task_types
        ]
        current_task_instance = self._create_task(self._testing_task_type, context)
        run_after_task_instances = [
            self._create_task(task_type, context) for task_type in run_after_synthesized_task_types
        ]
        all_task_instances = (
            run_before_task_instances + [current_task_instance] + run_after_task_instances
        )

        try:
            for tsk in all_task_instances:
                tsk.execute()
        except Exception as e:
            # TODO(#7644): Remove this hack before anything more starts relying on it!
            setattr(e, "_context", context)
            raise e

        return self.TaskInvocationResult(
            context=context,
            before_tasks=tuple(run_before_task_instances),
            this_task=current_task_instance,
            after_tasks=tuple(run_after_task_instances),
        )
