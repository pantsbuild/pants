# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
from contextlib import closing
from StringIO import StringIO

from pants.cache.cache_setup import CacheFactory
from pants.goal.goal import Goal
from pants.ivy.bootstrapper import Bootstrapper
from pants.task.console_task import ConsoleTask
from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
from pants_test.base_test import BaseTest


# TODO: Find a better home for this?
def is_exe(name):
  result = subprocess.call(['which', name], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
  return result == 0


def ensure_cached(task_cls, expected_num_artifacts=None):
  """Decorator for a task-executing unit test. Asserts that after running
  the decorated test function, the cache for task_cls contains expected_num_artifacts.
  Clears the task's cache before running the test.

  :API: public

  :param task_cls: Class of the task to check the artifact cache for. (e.g. JarCreate)
  :param expected_num_artifacts: Expected number of artifacts to be in the task's
                                 cache after running the test. If unspecified, will
                                 assert that the number of artifacts in the cache is
                                 non-zero.
  """
  def decorator(test_fn):

    def wrapper(self, *args, **kwargs):
      with temporary_dir() as artifact_cache:
        self.set_options_for_scope('cache.{}'.format(self.options_scope),
                                   write_to=[artifact_cache])
        self.set_options_for_scope('cache.{}'.format(task_cls.options_scope),
                                   write_to=[artifact_cache])
        # TODO: explain that this works because we can assume the cache
        # directory starts with the stable_name() -- see cache_setup.py

        # task_cache = os.path.join(artifact_cache, task_cls.stable_name())
        # os.mkdir(task_cache)

        test_fn(self, *args, **kwargs)

        cache_subdir_glob_str = os.path.join(
          artifact_cache,
          CacheFactory.make_task_cache_glob_str(task_cls))
        print('cache_subdir_glob_str: {}'.format(cache_subdir_glob_str))
        cache_subdirs = glob.glob(cache_subdir_glob_str)
        print('cache subdirs: {}'.format(os.listdir(artifact_cache)))

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

    return wrapper

  return decorator


class TaskTestBase(BaseTest):
  """A baseclass useful for testing a single Task type.

  :API: public
  """

  options_scope = 'test_scope'

  @classmethod
  def task_type(cls):
    """Subclasses must return the type of the Task subclass under test.

    :API: public
    """
    raise NotImplementedError()

  def setUp(self):
    """
    :API: public
    """
    super(TaskTestBase, self).setUp()
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
    subclass_name = b'test_{0}_{1}'.format(task_type.__name__, options_scope)
    return type(subclass_name, (task_type,), {'_stable_name': task_type._compute_stable_name(),
                                              'options_scope': options_scope})

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
    return super(TaskTestBase, self).context(for_task_types=for_task_types, **kwargs)

  def create_task(self, context, workdir=None):
    """
    :API: public
    """
    if workdir is None:
      workdir = self.test_workdir
    return self._testing_task_type(context, workdir)


class ConsoleTaskTestBase(TaskTestBase):
  """A base class useful for testing ConsoleTasks.

  :API: public
  """

  def setUp(self):
    """
    :API: public
    """
    Goal.clear()
    super(ConsoleTaskTestBase, self).setUp()

    task_type = self.task_type()
    assert issubclass(task_type, ConsoleTask), \
        'task_type() must return a ConsoleTask subclass, got %s' % task_type

  def execute_task(self, targets=None, options=None):
    """Creates a new task and executes it with the given config, command line args and targets.

    :API: public

    :param targets: Optional list of Target objects passed on the command line.
    Returns the text output of the task.
    """
    options = options or {}
    with closing(StringIO()) as output:
      self.set_options(**options)
      context = self.context(target_roots=targets, console_outstream=output)
      task = self.create_task(context)
      task.execute()
      return output.getvalue()

  def execute_console_task(self, targets=None, extra_targets=None, options=None,
                           passthru_args=None, workspace=None):
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
    context = self.context(target_roots=targets, passthru_args=passthru_args, workspace=workspace)
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
    return list(task.console_output(list(task.context.targets()) + list(extra_targets or ())))

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
    self.assertEqual(sorted(list(output) + ['']), sorted((self.execute_task(**kwargs)).split(sep)))

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
