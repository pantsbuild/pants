# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.option.optionable import Optionable
from pants.option.options import Options


class GlobalOptionsRegistrar(Optionable):
  options_scope = Options.GLOBAL_SCOPE

  @classmethod
  def register_bootstrap_options(cls, register):
    """Register bootstrap options.

    "Bootstrap options" are a small set of options whose values are useful when registering other
    options. Therefore we must bootstrap them early, before other options are registered, let
    alone parsed.

    Bootstrap option values can be interpolated into the config file, and can be referenced
    programatically in registration code, e.g., as register.bootstrap.pants_workdir.

    Note that regular code can also access these options as normal global-scope options. Their
    status as "bootstrap options" is only pertinent during option registration.
    """
    buildroot = get_buildroot()
    register('--plugins', advanced=True, type=Options.list, help='Load these plugins.')
    register('--backend-packages', advanced=True, type=Options.list,
             help='Load backends from these packages that are already on the path.')

    register('--pants-bootstrapdir', advanced=True, metavar='<dir>', default=get_pants_cachedir(),
             help='Use this dir for global cache.')
    register('--pants-configdir', advanced=True, metavar='<dir>', default=get_pants_configdir(),
             help='Use this dir for global config files.')
    register('--pants-workdir', metavar='<dir>', default=os.path.join(buildroot, '.pants.d'),
             help='Write intermediate output files to this dir.')
    register('--pants-supportdir', metavar='<dir>',
             default=os.path.join(buildroot, 'build-support'),
             help='Use support files from this dir.')
    register('--pants-distdir', metavar='<dir>', default=os.path.join(buildroot, 'dist'),
             help='Write end-product artifacts to this dir.')
    register('--config-override', help='A second config file, to override pants.ini.')
    register('--pantsrc', action='store_true', default=True,
             help='Use pantsrc files.')
    register('--pantsrc-files', action='append', metavar='<path>',
             default=['/etc/pantsrc', '~/.pants.rc'],
             help='Override config with values from these files. '
                  'Later files override earlier ones.')
    register('--pythonpath', action='append',
             help='Add these directories to PYTHONPATH to search for plugins.')
    register('--target-spec-file', action='append', dest='target_spec_files',
             help='Read additional specs from this file, one per line')

    # These logging options are registered in the bootstrap phase so that plugins can log during
    # registration and not so that their values can be interpolated in configs.
    register('-d', '--logdir', metavar='<dir>',
             help='Write logs to files under this directory.')

    # Although logging supports the WARN level, its not documented and could conceivably be yanked.
    # Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
    # setup a 'WARN' logging level name that maps to 'WARNING'.
    logging.addLevelName(logging.WARNING, 'WARN')
    register('-l', '--level', choices=['debug', 'info', 'warn'], default='info', recursive=True,
             help='Set the logging level.')

    register('-q', '--quiet', action='store_true',
             help='Squelches all console output apart from errors.')

  @classmethod
  def register_options(cls, register):
    """Register options not tied to any particular task or subsystem."""
    # The bootstrap options need to be registered on the post-bootstrap Options instance, so it
    # won't choke on them on the command line, and also so we can access their values as regular
    # global-scope options, for convenience.
    cls.register_bootstrap_options(register)

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
    register('--max-subprocess-args', type=int, default=100,  advanced=True, recursive=True,
             help='Used to limit the number of arguments passed to some subprocesses by breaking'
             'the command up into multiple invocations')
    register('--build-file-rev',
             help='Read BUILD files from this scm rev instead of from the working tree.  This is '
             'useful for implementing pants-aware sparse checkouts.')
