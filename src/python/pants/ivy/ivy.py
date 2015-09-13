# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from six import string_types
from twitter.common.collections import maybe_list

from pants.java import util
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import Executor, SubprocessExecutor


class Ivy(object):
  """Encapsulates the ivy cli taking care of the basic invocation letting you just worry about the
  args to pass to the cli itself.
  """

  class Error(Exception):
    """Indicates an error executing an ivy command."""

  def __init__(self, classpath, ivy_settings=None, ivy_cache_dir=None, extra_jvm_options=None):
    """Configures an ivy wrapper for the ivy distribution at the given classpath.

    :param ivy_settings: path to find settings.xml file
    :param ivy_cache_dir: path to store downloaded ivy artifacts
    :param extra_jvm_options: list of strings to add to command line when invoking Ivy
    """
    self._classpath = maybe_list(classpath)
    self._ivy_settings = ivy_settings
    if self._ivy_settings and not isinstance(self._ivy_settings, string_types):
      raise ValueError('ivy_settings must be a string, given {} of type {}'.format(
                         self._ivy_settings, type(self._ivy_settings)))

    self._ivy_cache_dir = ivy_cache_dir
    if self._ivy_cache_dir and not isinstance(self._ivy_cache_dir, string_types):
      raise ValueError('ivy_cache_dir must be a string, given {} of type {}'.format(
                         self._ivy_cache_dir, type(self._ivy_cache_dir)))

    self._extra_jvm_options = extra_jvm_options or []

  @property
  def ivy_settings(self):
    """Returns the ivysettings.xml path used by this `Ivy` instance.

    May be None if ivy's built in default ivysettings.xml of standard public resolvers is being
    used.
    """
    return self._ivy_settings

  @property
  def ivy_cache_dir(self):
    """Returns the ivy cache dir used by this `Ivy` instance."""
    return self._ivy_cache_dir

  def execute(self, jvm_options=None, args=None, executor=None,
              workunit_factory=None, workunit_name=None, workunit_labels=None):
    """Executes the ivy commandline client with the given args.

    Raises Ivy.Error if the command fails for any reason.
    :param executor: Java executor to run ivy with.
    """
    # NB(gmalmquist): It should be OK that we can't declare a subsystem_dependency in this file
    # (because it's just a plain old object), because Ivy is only constructed by Bootstrapper, which
    # makes an explicit call to IvySubsystem.global_instance() in its constructor, which in turn has
    # a declared dependency on DistributionLocator.
    executor = executor or SubprocessExecutor(DistributionLocator.cached())
    runner = self.runner(jvm_options=jvm_options, args=args, executor=executor)
    try:
      result = util.execute_runner(runner, workunit_factory, workunit_name, workunit_labels)
      if result != 0:
        raise self.Error('Ivy command failed with exit code {}{}'.format(
                           result, ': ' + ' '.join(args) if args else ''))
    except executor.Error as e:
      raise self.Error('Problem executing ivy: {}'.format(e))

  def runner(self, jvm_options=None, args=None, executor=None):
    """Creates an ivy commandline client runner for the given args."""
    args = args or []
    jvm_options = jvm_options or []
    executor = executor or SubprocessExecutor(DistributionLocator.cached())
    if not isinstance(executor, Executor):
      raise ValueError('The executor argument must be an Executor instance, given {} of type {}'.format(
                         executor, type(executor)))

    if self._ivy_cache_dir and '-cache' not in args:
      # TODO(John Sirois): Currently this is a magic property to support hand-crafted <caches/> in
      # ivysettings.xml.  Ideally we'd support either simple -caches or these hand-crafted cases
      # instead of just hand-crafted.  Clean this up by taking over ivysettings.xml and generating
      # it from BUILD constructs.
      jvm_options += ['-Divy.cache.dir={}'.format(self._ivy_cache_dir)]

    if self._ivy_settings and '-settings' not in args:
      args = ['-settings', self._ivy_settings] + args

    jvm_options += self._extra_jvm_options
    return executor.runner(classpath=self._classpath, main='org.apache.ivy.Main',
                           jvm_options=jvm_options, args=args)
