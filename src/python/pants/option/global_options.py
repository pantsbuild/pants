# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.build_environment import (get_buildroot, get_pants_cachedir, get_pants_configdir,
                                          pants_version)
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.custom_types import list_option
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo


class GlobalOptionsRegistrar(Optionable):
  options_scope = GLOBAL_SCOPE
  options_scope_category = ScopeInfo.GLOBAL

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

    # Although logging supports the WARN level, its not documented and could conceivably be yanked.
    # Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
    # setup a 'WARN' logging level name that maps to 'WARNING'.
    logging.addLevelName(logging.WARNING, 'WARN')
    register('-l', '--level', choices=['debug', 'info', 'warn'], default='info', recursive=True,
             help='Set the logging level.')
    register('-q', '--quiet', action='store_true',
             help='Squelches all console output apart from errors.')
    # Not really needed in bootstrap options, but putting it here means it displays right
    # after -l and -q in help output, which is conveniently contextual.
    register('--colors', action='store_true', default=True, recursive=True,
             help='Set whether log messages are displayed in color.')

    # NB: Right now this option is a placeholder that is unused within pants itself except when
    # specified on the command line to print the OSS pants version.  Both the IntelliJ Pants plugin
    # and the pantsbuild/setup bootstrap script grep for pants_version though so this option
    # registration serves in part as documentation of the dependency.
    # TODO(John Sirois): Move pantsbuild.pants bootstrapping into pants itself and have it use this
    # version option directly.
    register('-V', '--pants-version', '--version',  # NB: pants_version is the 1st long option
                                                    # since that's the one read from pants.ini;
                                                    # the version form only works from the CLI.
             nargs='?',  # Allows using the flag with no args on the CLI to print version as well
                         # as setting the version in pants.ini
             default=pants_version(),  # Displays the current version correctly in `./pants -h`.
             const=pants_version(),  # Displays the current version via `./pants -V`.
             help="Prints pants' version number and exits.")

    register('--plugins', advanced=True, type=list_option, help='Load these plugins.')
    register('--plugin-cache-dir', advanced=True,
             default=os.path.join(get_pants_cachedir(), 'plugins'),
             help='Cache resolved plugin requirements here.')

    register('--backend-packages', advanced=True, type=list_option,
             help='Load backends from these packages that are already on the path.')

    register('--pants-bootstrapdir', advanced=True, metavar='<dir>', default=get_pants_cachedir(),
             help='Use this dir for global cache.')
    register('--pants-configdir', advanced=True, metavar='<dir>', default=get_pants_configdir(),
             help='Use this dir for global config files.')
    register('--pants-workdir', advanced=True, metavar='<dir>',
             default=os.path.join(buildroot, '.pants.d'),
             help='Write intermediate output files to this dir.')
    register('--pants-supportdir', advanced=True, metavar='<dir>',
             default=os.path.join(buildroot, 'build-support'),
             help='Use support files from this dir.')
    register('--pants-distdir', advanced=True, metavar='<dir>',
             default=os.path.join(buildroot, 'dist'),
             help='Write end-product artifacts to this dir.')
    register('--config-override', advanced=True, action='append', metavar='<path>',
             help='A second config file, to override pants.ini.')
    register('--pantsrc', advanced=True, action='store_true', default=True,
             help='Use pantsrc files.')
    register('--pantsrc-files', advanced=True, action='append', metavar='<path>',
             default=['/etc/pantsrc', '~/.pants.rc'],
             help='Override config with values from these files. '
                  'Later files override earlier ones.')
    register('--pythonpath', advanced=True, action='append',
             help='Add these directories to PYTHONPATH to search for plugins.')
    register('--target-spec-file', action='append', dest='target_spec_files',
             help='Read additional specs from this file, one per line')

    # These logging options are registered in the bootstrap phase so that plugins can log during
    # registration and not so that their values can be interpolated in configs.
    register('-d', '--logdir', advanced=True, metavar='<dir>',
             help='Write logs to files under this directory.')

  @classmethod
  def register_options(cls, register):
    """Register options not tied to any particular task or subsystem."""
    # The bootstrap options need to be registered on the post-bootstrap Options instance, so it
    # won't choke on them on the command line, and also so we can access their values as regular
    # global-scope options, for convenience.
    cls.register_bootstrap_options(register)

    register('-x', '--time', action='store_true',
             help='Output a timing report at the end of the run.')
    register('-e', '--explain', action='store_true',
             help='Explain the execution of goals.')
    register('--tag', action='append', metavar='[+-]tag1,tag2,...',
             help="Include only targets with these tags (optional '+' prefix) or without these "
                  "tags ('-' prefix).  Useful with ::, to find subsets of targets "
                  "(e.g., integration tests.)")

    register('-t', '--timeout', advanced=True, type=int, metavar='<seconds>',
             help='Number of seconds to wait for http connections.')
    # TODO: After moving to the new options system these abstraction leaks can go away.
    register('-k', '--kill-nailguns', advanced=True, action='store_true',
             help='Kill nailguns before exiting')
    register('-i', '--interpreter', advanced=True, default=[], action='append',
             metavar='<requirement>',
             help="Constrain what Python interpreters to use.  Uses Requirement format from "
                  "pkg_resources, e.g. 'CPython>=2.6,<3' or 'PyPy'. By default, no constraints "
                  "are used.  Multiple constraints may be added.  They will be ORed together.")
    register('--exclude-target-regexp', advanced=True, action='append', default=[],
             metavar='<regexp>',
             help='Exclude targets that match these regexes. Useful with ::, to ignore broken '
                  'BUILD files.',
             recursive=True)  # TODO: Does this need to be recursive? What does that even mean?
    register('--spec-excludes', advanced=True, action='append',
             default=[register.bootstrap.pants_workdir],
             help='Ignore these paths when evaluating the command-line target specs.  Useful with '
                  '::, to avoid descending into unneeded directories.')
    register('--fail-fast', advanced=True, action='store_true',
             help='When parsing specs, will stop on the first erronous BUILD file encountered. '
                  'Otherwise, will parse all builds in a spec and then display an error.')
    register('--cache-key-gen-version', advanced=True, default='200', recursive=True,
             help='The cache key generation. Bump this to invalidate every artifact for a scope.')
    register('--max-subprocess-args', advanced=True, type=int, default=100, recursive=True,
             help='Used to limit the number of arguments passed to some subprocesses by breaking '
             'the command up into multiple invocations')
    register('--print-exception-stacktrace', advanced=True, action='store_true',
             help='Print to console the full exception stack trace if encountered.')
    register('--build-file-rev', advanced=True,
             help='Read BUILD files from this scm rev instead of from the working tree.  This is '
             'useful for implementing pants-aware sparse checkouts.')
    register('--lock', advanced=True, action='store_true', default=True,
             help='Use a global lock to exclude other versions of pants from running during '
                  'critical operations.')
