# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import maybe_list
from twitter.common.lang import Compatibility

from pants.java import util
from pants.java.executor import Executor, SubprocessExecutor


class Ivy(object):
  """Encapsulates the ivy cli taking care of the basic invocation letting you just worry about the
  args to pass to the cli itself.
  """

  class Error(Exception):
    """Indicates an error executing an ivy command."""

  def __init__(self, classpath, java_executor=None, ivy_settings=None, ivy_cache_dir=None):
    """Configures an ivy wrapper for the ivy distribution at the given classpath."""

    self._classpath = maybe_list(classpath)

    self._java = java_executor or SubprocessExecutor()
    if not isinstance(self._java, Executor):
      raise ValueError('java_executor must be an Executor instance, given %s of type %s'
                       % (self._java, type(self._java)))

    self._ivy_settings = ivy_settings
    if self._ivy_settings and not isinstance(self._ivy_settings, Compatibility.string):
      raise ValueError('ivy_settings must be a string, given %s of type %s'
                       % (self._ivy_settings, type(self._ivy_settings)))

    self._ivy_cache_dir = ivy_cache_dir
    if self._ivy_cache_dir and not isinstance(self._ivy_cache_dir, Compatibility.string):
      raise ValueError('ivy_cache_dir must be a string, given %s of type %s'
                       % (self._ivy_cache_dir, type(self._ivy_cache_dir)))

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
    """
    runner = self.runner(jvm_options=jvm_options, args=args, executor=executor)
    try:
      result = util.execute_runner(runner, workunit_factory, workunit_name, workunit_labels)
      if result != 0:
        raise self.Error('Ivy command failed with exit code %d%s'
                         % (result, ': ' + ' '.join(args) if args else ''))
    except self._java.Error as e:
      raise self.Error('Problem executing ivy: %s' % e)

  def runner(self, jvm_options=None, args=None, executor=None):
    """Creates an ivy commandline client runner for the given args."""
    args = args or []
    executor = executor or self._java
    if not isinstance(executor, Executor):
      raise ValueError('The executor argument must be an Executor instance, given %s of type %s'
                       % (executor, type(executor)))

    if self._ivy_cache_dir and '-cache' not in args:
      # TODO(John Sirois): Currently this is a magic property to support hand-crafted <caches/> in
      # ivysettings.xml.  Ideally we'd support either simple -caches or these hand-crafted cases
      # instead of just hand-crafted.  Clean this up by taking over ivysettings.xml and generating
      # it from BUILD constructs.
      jvm_options = ['-Divy.cache.dir=%s' % self._ivy_cache_dir] + (jvm_options or [])

    if self._ivy_settings and '-settings' not in args:
      args = ['-settings', self._ivy_settings] + args

    return executor.runner(classpath=self._classpath, main='org.apache.ivy.Main',
                           jvm_options=jvm_options, args=args)
