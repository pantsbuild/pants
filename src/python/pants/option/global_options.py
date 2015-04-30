# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.options import Options


def register_global_options(register):
  """Register options not tied to any particular task.

  It's important to note that another set of global options is registered in
  `pants.option.options_bootstrapper:register_bootstrap_options`, but those are reserved for options
  that other options or tasks may need to build upon directly or indirectly.  For a direct-use
  example, a doc generation task may want to provide an option for its user-visible output location
  that defaults to `${pants-distdir}/docs` and thus needs to interpolate the bootstrap option of
  `pants-distdir`.  An indirect example would be logging options that are needed by pants itself to
  setup logging prior to loading plugins so that plugin registration can log confidently to a
  configured logging subsystem.

  Global options here on the other hand are reserved for infrastructure objects (not tasks) that
  have leaf configuration data.
  """
  register('-t', '--timeout', type=int, metavar='<seconds>',
           help='Number of seconds to wait for http connections.')
  register('-x', '--time', action='store_true',
           help='Times tasks and goals and outputs a report.')
  register('-e', '--explain', action='store_true',
           help='Explain the execution of goals.')

  # TODO: After moving to the new options system these abstraction leaks can go away.
  register('-k', '--kill-nailguns', action='store_true',
           help='Kill nailguns before exiting')
  register('-i', '--interpreter', default=[], action='append', metavar='<requirement>',
           help="Constrain what Python interpreters to use.  Uses Requirement format from "
                "pkg_resources, e.g. 'CPython>=2.6,<3' or 'PyPy'. By default, no constraints "
                "are used.  Multiple constraints may be added.  They will be ORed together.")
  register('--colors', action='store_true', default=True, recursive=True,
           help='Set whether log messages are displayed in color.')
  register('--spec-excludes', action='append', default=[register.bootstrap.pants_workdir],
           help='Exclude these paths when computing the command-line target specs.')
  register('--exclude-target-regexp', action='append', default=[], metavar='<regexp>',
           help='Regex pattern to exclude from the target list (useful in conjunction with ::). '
                'Multiple patterns may be specified by setting this flag multiple times.',
           recursive=True)
  # TODO: When we have a model for 'subsystems', create one for artifact caching and move these
  # options to there. When we do that, also drop the cumbersome word 'artifact' from these
  # option names. There's only one cache concept that users care about.
  register('--read-from-artifact-cache', action='store_true', default=True, recursive=True,
           help='Read build artifacts from cache, if available.')
  register('--read-artifact-caches', type=Options.list, recursive=True,
           help='The URIs of artifact caches to read from. Each entry is a URL of a RESTful cache, '
                'a path of a filesystem cache, or a pipe-separated list of alternate caches to '
                'choose from.')
  register('--write-to-artifact-cache', action='store_true', default=True, recursive=True,
           help='Write build artifacts to cache, if possible.')
  register('--write-artifact-caches', type=Options.list, recursive=True,
           help='The URIs of artifact caches to write to. Each entry is a URL of a RESTful cache, '
                'a path of a filesystem cache, or a pipe-separated list of alternate caches to '
                'choose from.')
  register('--overwrite-cache-artifacts', action='store_true', recursive=True,
           help='If writing to build artifacts to cache, overwrite (instead of skip) existing.')
  register('--cache-key-gen-version', advanced=True, default='200', recursive=True,
           help='The cache key generation. Bump this to invalidate every artifact for a scope.')
  register('--cache-compression', advanced=True, type=int, default=5, recursive=True,
           help='The gzip compression level for created artifacts.')
  register('--print-exception-stacktrace', action='store_true',
           help='Print to console the full exception stack trace if encountered.')
  register('--fail-fast', action='store_true',
           help='When parsing specs, will stop on the first erronous BUILD file encountered. '
                'Otherwise, will parse all builds in a spec and then throw an Exception.')
  register('--python-chroot-requirements-ttl', type=int, metavar='<seconds>',
           default=10 * 365 * 86400,  # 10 years.
           help='the time in seconds before we consider re-resolving an open-ended '
                'requirement, e.g. "flask>=0.2" if a matching distribution is available on disk.')
  register('--pants-support-baseurls', type=Options.list, advanced=True, recursive=True,
           default = [ 'https://dl.bintray.com/pantsbuild/bin/build-support' ],
           help='List of urls from which binary tools are downloaded.  Urls are searched in order'
           'until the requested path is found.')
  register('--max-subprocess-args', type=int, default=100,  advanced=True, recursive=True,
           help='Used to limit the number of arguments passed to some subprocesses by breaking'
           'the command up into multiple invocations')
  register('--pants-support-fetch-timeout-secs', type=int, default=30, advanced=True, recursive=True,
           help='Timeout in seconds for url reads when fetching binary tools from the '
                'repos specified by --pants-support-baseurls')
  register('--build-file-rev',
           help='Read BUILD files from this scm rev instead of from the working tree.  This is '
           'useful for implementing pants-aware sparse checkouts.')

  # The following options are specific to java_thrift_library targets.
  register('--thrift-default-compiler', type=str, advanced=True, default='thrift',
           help='The default compiler to use for java_thrift_library targets.')
  register('--thrift-default-language', type=str, advanced=True, default='java',
           help='The default language to generate for java_thrift_library targets.')
  register('--thrift-default-rpc-style', type=str, advanced=True, default='sync',
           help='The default rpc-style to generate for java_thrift_library targets.')
