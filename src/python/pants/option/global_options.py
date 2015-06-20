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
           help='Ignore these paths when evaluating the command-line target specs.  Useful with '
                '::, to avoid descending into unneeded directories.')
  register('--exclude-target-regexp', action='append', default=[], metavar='<regexp>',
           help='Exclude targets that match these regexes. Useful with ::, to ignore broken '
                'BUILD files.',
           recursive=True)  # TODO: Does this need to be recursive? What does that even mean?
  register('--tag', action='append', metavar='[+-]tag1,tag2,...',
           help="Include only targets with these tags (optional '+' prefix) or without these "
                "tags ('-' prefix).  Useful with ::, to find subsets of targets "
                "(e.g., integration tests.)")
  register('--cache-key-gen-version', advanced=True, default='200', recursive=True,
           help='The cache key generation. Bump this to invalidate every artifact for a scope.')
  register('--print-exception-stacktrace', action='store_true',
           help='Print to console the full exception stack trace if encountered.')
  register('--fail-fast', action='store_true',
           help='When parsing specs, will stop on the first erronous BUILD file encountered. '
                'Otherwise, will parse all builds in a spec and then throw an Exception.')
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
