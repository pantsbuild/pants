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

  def __init__(
    self,
    classpath,
    ivy_settings=None,
    ivy_cache_dir=None,
    ivy_resolution_dir=None,
    extra_jvm_options=None,
  ):
    """Configures an ivy wrapper for the ivy distribution at the given classpath.

    :param ivy_settings: path to find settings.xml file
    :param ivy_cache_dir: path to store downloaded ivy artifacts
    :param ivy_resolution_dir: path Ivy will use as a resolution scratch space
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

    self._ivy_resolution_dir = ivy_resolution_dir
    if self._ivy_resolution_dir and not isinstance(self._ivy_resolution_dir, string_types):
      raise ValueError('ivy_resolution_dir must be a string, given {} of type {}'.format(
                         self._ivy_resolution_dir, type(self._ivy_resolution_dir)))

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

  @property
  def ivy_resolution_dir(self):
    """Returns the ivy resolution dir used by this `Ivy` instance."""
    return self._ivy_resolution_dir

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
    jvm_args = []
    jvm_options = jvm_options or []
    executor = executor or SubprocessExecutor(DistributionLocator.cached())
    if not isinstance(executor, Executor):
      raise ValueError('The executor argument must be an Executor instance, given {} of type {}'.format(
                         executor, type(executor)))

    # If '-cache' is in the provided args, it is assumed that the caller is taking full control
    # over caching conventions, including passing the appropriate '-settings' and
    # JVM properties for repository/resolution directories if custom ones are defined.
    if '-cache' not in args:
      # At the broadest scope, treat `--ivy-cache-dir` as the default global cache.
      # This can be refined for narrower cache scopes, in particular for resolution.
      jvm_args.extend(['-cache', self._ivy_cache_dir])
      if self._ivy_resolution_dir != self._ivy_cache_dir:
        if not self._ivy_settings:
          raise self.Error(
            '--ivy-resolution-dir is configured to be separate from --ivy-cache-dir,'
            ' but a custom --ivy-ivy-settings pointing to an'
            ' ivysettings.xml file was not provided.  In order for pants to discover the resolution'
            ' reports that ivy generates, a custom ivysettings.xml defining <cache/> must be'
            ' provided.  See build-support/ivy/ivysettings.xml in the pants repo for an example.'
          )
        jvm_args.extend(['-settings', self._ivy_settings])
        # TODO(Patrick Lawson): In this case, the defaultCacheDir and resolutionCacheDir properties
        #  _must_ be set to ${ivy.cache.repository.dir} and ${ivy.cache.resolution.dir} respectively
        # in the <caches/> section of the passed ivy_settings XML file.
        # Pants expects to rebase fetched artifacts from self._ivy_cache_dir,
        # and it will look for generated resolution reports in self._ivy_resolution_dir.
        jvm_options.extend([
          '-Divy.cache.repository.dir={}'.format(self._ivy_cache_dir),
          '-Divy.cache.resolution.dir={}'.format(self._ivy_resolution_dir),
        ])

    jvm_options += self._extra_jvm_options
    # NOTE(Patrick Lawson): It's important to prepend our arguments, since
    # ivy can be used to invoke the JVM with the appropriate classpath
    # after resolution, at which point it needs the trailing args in the right
    # order.
    jvm_args.extend(args)
    return executor.runner(classpath=self._classpath, main='org.apache.ivy.Main',
                           jvm_options=jvm_options, args=jvm_args)
