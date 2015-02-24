# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.options import Options


def register_global_options(register):
  register('-t', '--timeout', type=int, metavar='<seconds>',
           help='Number of seconds to wait for http connections.')
  register('-x', '--time', action='store_true',
           help='Times tasks and goals and outputs a report.')
  register('-e', '--explain', action='store_true',
           help='Explain the execution of goals.')

  # TODO: After moving to the new options system these abstraction leaks can go away.
  register('-k', '--kill-nailguns', action='store_true',
           help='Kill nailguns before exiting')
  register('--ng-daemons', action='store_true', default=True,
           help='Use nailgun daemons to execute java tasks.')

  register('-d', '--logdir', metavar='<dir>',
           help='Write logs to files under this directory.')
  register('-l', '--level', choices=['debug', 'info', 'warn'], default='info',
           help='Set the logging level.')
  register('-q', '--quiet', action='store_true',
           help='Squelches all console output apart from errors.')
  register('-i', '--interpreter', default=[], action='append', metavar='<requirement>',
           help="Constrain what Python interpreters to use.  Uses Requirement format from "
                "pkg_resources, e.g. 'CPython>=2.6,<3' or 'PyPy'. By default, no constraints "
                "are used.  Multiple constraints may be added.  They will be ORed together.")
  register('--colors', action='store_true', default=True,
           help='Set whether log messages are displayed in color.')
  register('--spec-excludes', action='append', default=[register.bootstrap.pants_workdir],
           help='Exclude these paths when computing the command-line target specs.')
  register('--exclude-target-regexp', action='append', default=[], metavar='<regexp>',
           help='Regex pattern to exclude from the target list (useful in conjunction with ::). '
                'Multiple patterns may be specified by setting this flag multiple times.')
  # TODO: When we have a model for 'subsystems', create one for artifact caching and move these
  # options to there. When we do that, also drop the cumbersome word 'artifact' from these
  # option names. There's only one cache concept that users care about.
  register('--read-from-artifact-cache', action='store_true', default=True,
           help='Read build artifacts from cache, if available.')
  register('--read-artifact-caches', type=Options.list,
           help='The URIs of artifact caches to read from. Each entry is a URL of a RESTful cache, '
                'a path of a filesystem cache, or a pipe-separated list of alternate caches to '
                'choose from.')
  register('--write-to-artifact-cache', action='store_true', default=True,
           help='Write build artifacts to cache, if possible.')
  register('--write-artifact-caches', type=Options.list,
           help='The URIs of artifact caches to write to. Each entry is a URL of a RESTful cache, '
                'a path of a filesystem cache, or a pipe-separated list of alternate caches to '
                'choose from.')
  register('--overwrite-cache-artifacts', action='store_true',
           help='If writing to build artifacts to cache, overwrite (instead of skip) existing.')
  register('--cache-key-gen-version', advanced=True, default='200',
           help='The cache key generation. Bump this to invalidate every artifact.')
  register('--cache-compression', advanced=True, type=int, default=5,
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
