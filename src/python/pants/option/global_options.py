# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import multiprocessing
import os
import sys

from pants.base.build_environment import (get_buildroot, get_default_pants_config_file,
                                          get_pants_cachedir, get_pants_configdir, pants_version)
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.custom_types import dir_option
from pants.option.errors import OptionsError
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin
from pants.util.objects import datatype, enum


class GlobMatchErrorBehavior(enum('failure_behavior', ['ignore', 'warn', 'error'])):
  """Describe the action to perform when matching globs in BUILD files to source files.

  NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will need to
  be aware of any changes to this object's definition.
  """

  default_option_value = 'warn'


class ExecutionOptions(datatype([
  'remote_store_server',
  'remote_store_thread_count',
  'remote_execution_server',
  'remote_store_chunk_bytes',
  'remote_store_chunk_upload_timeout_seconds',
  'process_execution_parallelism',
  'process_execution_cleanup_local_dirs',
  'remote_instance_name',
  'remote_ca_certs_path',
  'remote_oauth_bearer_token_path',
])):
  """A collection of all options related to (remote) execution of processes.

  TODO: These options should move to a Subsystem once we add support for "bootstrap" Subsystems (ie,
  allowing Subsystems to be consumed before the Scheduler has been created).
  """

  @classmethod
  def from_bootstrap_options(cls, bootstrap_options):
    return cls(
      remote_store_server=bootstrap_options.remote_store_server,
      remote_execution_server=bootstrap_options.remote_execution_server,
      remote_store_thread_count=bootstrap_options.remote_store_thread_count,
      remote_store_chunk_bytes=bootstrap_options.remote_store_chunk_bytes,
      remote_store_chunk_upload_timeout_seconds=bootstrap_options.remote_store_chunk_upload_timeout_seconds,
      process_execution_parallelism=bootstrap_options.process_execution_parallelism,
      process_execution_cleanup_local_dirs=bootstrap_options.process_execution_cleanup_local_dirs,
      remote_instance_name=bootstrap_options.remote_instance_name,
      remote_ca_certs_path=bootstrap_options.remote_ca_certs_path,
      remote_oauth_bearer_token_path=bootstrap_options.remote_oauth_bearer_token_path,
    )


DEFAULT_EXECUTION_OPTIONS = ExecutionOptions(
    remote_store_server=None,
    remote_store_thread_count=1,
    remote_execution_server=None,
    remote_store_chunk_bytes=1024*1024,
    remote_store_chunk_upload_timeout_seconds=60,
    process_execution_parallelism=multiprocessing.cpu_count()*2,
    process_execution_cleanup_local_dirs=True,
    remote_instance_name=None,
    remote_ca_certs_path=None,
    remote_oauth_bearer_token_path=None,
  )


class GlobalOptionsRegistrar(SubsystemClientMixin, Optionable):
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
    default_distdir_name = 'dist'
    default_distdir = os.path.join(buildroot, default_distdir_name)
    default_rel_distdir = '/{}/'.format(default_distdir_name)

    register('-l', '--level', choices=['trace', 'debug', 'info', 'warn'], default='info',
             recursive=True, help='Set the logging level.')
    register('-q', '--quiet', type=bool, recursive=True, daemon=False,
             help='Squelches most console output. NOTE: Some tasks default to behaving quietly: '
                  'inverting this option supports making them noisier than they would be otherwise.')

    # Not really needed in bootstrap options, but putting it here means it displays right
    # after -l and -q in help output, which is conveniently contextual.
    register('--colors', type=bool, default=sys.stdout.isatty(), recursive=True, daemon=False,
             help='Set whether log messages are displayed in color.')

    # Pants code uses this only to verify that we are of the requested version. However
    # setup scripts, runner scripts, IDE plugins, etc., may grep this out of pants.ini
    # and use it to select the right version.
    # Note that to print the version of the pants instance you're running, use -v, -V or --version.
    register('--pants-version', advanced=True, default=pants_version(),
             help='Use this pants version.')

    register('--plugins', advanced=True, type=list, help='Load these plugins.')
    register('--plugin-cache-dir', advanced=True,
             default=os.path.join(get_pants_cachedir(), 'plugins'),
             help='Cache resolved plugin requirements here.')

    register('--backend-packages', advanced=True, type=list,
             default=['pants.backend.graph_info',
                      'pants.backend.python',
                      'pants.backend.jvm',
                      'pants.backend.native',
                      'pants.backend.codegen.antlr.java',
                      'pants.backend.codegen.antlr.python',
                      'pants.backend.codegen.jaxb',
                      'pants.backend.codegen.protobuf.java',
                      'pants.backend.codegen.ragel.java',
                      'pants.backend.codegen.thrift.java',
                      'pants.backend.codegen.thrift.python',
                      'pants.backend.codegen.wire.java',
                      'pants.backend.project_info'],
             help='Load backends from these packages that are already on the path. '
                  'Add contrib and custom backends to this list.')

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
             default=default_distdir,
             help='Write end-product artifacts to this dir. If you modify this path, you '
                  'should also update --build-ignore and --pants-ignore to include the '
                  'custom dist dir path as well.')
    register('--pants-subprocessdir', advanced=True, default=os.path.join(buildroot, '.pids'),
             help='The directory to use for tracking subprocess metadata, if any. This should '
                  'live outside of the dir used by `--pants-workdir` to allow for tracking '
                  'subprocesses that outlive the workdir data (e.g. `./pants server`).')
    register('--pants-config-files', advanced=True, type=list, daemon=False,
             default=[get_default_pants_config_file()], help='Paths to Pants config files.')
    # TODO: Deprecate the --pantsrc/--pantsrc-files options?  This would require being able
    # to set extra config file locations in an initial bootstrap config file.
    register('--pantsrc', advanced=True, type=bool, default=True,
             help='Use pantsrc files.')
    register('--pantsrc-files', advanced=True, type=list, metavar='<path>', daemon=False,
             default=['/etc/pantsrc', '~/.pants.rc'],
             help='Override config with values from these files. '
                  'Later files override earlier ones.')
    register('--pythonpath', advanced=True, type=list,
             help='Add these directories to PYTHONPATH to search for plugins.')
    register('--target-spec-file', type=list, dest='target_spec_files', daemon=False,
             help='Read additional specs from this file, one per line')
    register('--verify-config', type=bool, default=True, daemon=False,
             advanced=True,
             help='Verify that all config file values correspond to known options.')

    register('--build-ignore', advanced=True, type=list, fromfile=True,
             default=['.*/', default_rel_distdir, 'bower_components/',
                      'node_modules/', '*.egg-info/'],
             help='Paths to ignore when identifying BUILD files. '
                  'This does not affect any other filesystem operations. '
                  'Patterns use the gitignore pattern syntax (https://git-scm.com/docs/gitignore).')
    register('--pants-ignore', advanced=True, type=list, fromfile=True,
             default=['.*/', default_rel_distdir],
             help='Paths to ignore for all filesystem operations performed by pants '
                  '(e.g. BUILD file scanning, glob matching, etc). '
                  'Patterns use the gitignore syntax (https://git-scm.com/docs/gitignore).')
    register('--glob-expansion-failure', type=str,
             choices=GlobMatchErrorBehavior.allowed_values,
             default=GlobMatchErrorBehavior.default_option_value,
             advanced=True,
             help="Raise an exception if any targets declaring source files "
                  "fail to match any glob provided in the 'sources' argument.")

    register('--exclude-target-regexp', advanced=True, type=list, default=[], daemon=False,
             metavar='<regexp>', help='Exclude target roots that match these regexes.')
    register('--subproject-roots', type=list, advanced=True, fromfile=True, default=[],
             help='Paths that correspond with build roots for any subproject that this '
                  'project depends on.')
    register('--owner-of', type=list, default=[], daemon=False, fromfile=True, metavar='<path>',
             help='Select the targets that own these files. '
                  'This is the third target calculation strategy along with the --changed-* '
                  'options and specifying the targets directly. These three types of target '
                  'selection are mutually exclusive.')

    # These logging options are registered in the bootstrap phase so that plugins can log during
    # registration and not so that their values can be interpolated in configs.
    register('-d', '--logdir', advanced=True, metavar='<dir>',
             help='Write logs to files under this directory.')

    # This facilitates bootstrap-time configuration of pantsd usage such that we can
    # determine whether or not to use the Pailgun client to invoke a given pants run
    # without resorting to heavier options parsing.
    register('--enable-pantsd', advanced=True, type=bool, default=False,
             help='Enables use of the pants daemon (and implicitly, the v2 engine). (Beta)')

    # These facilitate configuring the native engine.
    register('--native-engine-visualize-to', advanced=True, default=None, type=dir_option, daemon=False,
             help='A directory to write execution and rule graphs to as `dot` files. The contents '
                  'of the directory will be overwritten if any filenames collide.')
    register('--print-exception-stacktrace', advanced=True, type=bool,
             help='Print to console the full exception stack trace if encountered.')

    # BinaryUtil options.
    register('--binaries-baseurls', type=list, advanced=True,
             default=['https://binaries.pantsbuild.org'],
             help='List of URLs from which binary tools are downloaded. URLs are '
                  'searched in order until the requested path is found.')
    register('--binaries-fetch-timeout-secs', type=int, default=30, advanced=True, daemon=False,
             help='Timeout in seconds for URL reads when fetching binary tools from the '
                  'repos specified by --baseurls.')
    register('--binaries-path-by-id', type=dict, advanced=True,
             help=("Maps output of uname for a machine to a binary search path: "
                   "(sysname, id) -> (os, arch), e.g. {('darwin', '15'): ('mac', '10.11'), "
                   "('linux', 'arm32'): ('linux', 'arm32')}."))
    register('--allow-external-binary-tool-downloads', type=bool, default=True, advanced=True,
             help="If False, require BinaryTool subclasses to download their contents from urls "
                  "generated from --binaries-baseurls, even if the tool has an external url "
                  "generator. This can be necessary if using Pants in an environment which cannot "
                  "contact the wider Internet.")

    # Pants Daemon options.
    register('--pantsd-pailgun-host', advanced=True, default='127.0.0.1',
             help='The host to bind the pants nailgun server to.')
    register('--pantsd-pailgun-port', advanced=True, type=int, default=0,
             help='The port to bind the pants nailgun server to. Defaults to a random port.')
    register('--pantsd-log-dir', advanced=True, default=None,
             help='The directory to log pantsd output to.')
    register('--pantsd-fs-event-workers', advanced=True, type=int, default=4,
             removal_version='1.14.0.dev2',
             removal_hint='Filesystem events are now handled by a single dedicated thread.',
             help='The number of workers to use for the filesystem event service executor pool.')
    register('--pantsd-invalidation-globs', advanced=True, type=list, fromfile=True, default=[],
             help='Filesystem events matching any of these globs will trigger a daemon restart.')

    # Watchman options.
    register('--watchman-version', advanced=True, default='4.9.0-pants1', help='Watchman version.')
    register('--watchman-supportdir', advanced=True, default='bin/watchman',
             help='Find watchman binaries under this dir. Used as part of the path to lookup '
                  'the binary with --binaries-baseurls and --pants-bootstrapdir.')
    register('--watchman-startup-timeout', type=float, advanced=True, default=30.0,
             help='The watchman socket timeout (in seconds) for the initial `watch-project` command. '
                  'This may need to be set higher for larger repos due to watchman startup cost.')
    register('--watchman-socket-timeout', type=float, advanced=True, default=0.1,
             help='The watchman client socket timeout in seconds. Setting this to too high a '
                  'value can negatively impact the latency of runs forked by pantsd.')
    register('--watchman-socket-path', type=str, advanced=True, default=None,
             help='The path to the watchman UNIX socket. This can be overridden if the default '
                  'absolute path length exceeds the maximum allowed by the OS.')

    # This option changes the parser behavior in a fundamental way (which currently invalidates
    # all caches), and needs to be parsed out early, so we make it a bootstrap option.
    register('--build-file-imports', choices=['allow', 'warn', 'error'], default='warn',
             advanced=True,
             help='Whether to allow import statements in BUILD files')

    register('--local-store-dir', advanced=True,
             help="Directory to use for engine's local file store.",
             # This default is also hard-coded into the engine's rust code in
             # fs::Store::default_path
             default=os.path.expanduser('~/.cache/pants/lmdb_store'))
    register('--remote-store-server', advanced=True,
             help='host:port of grpc server to use as remote execution file store.')
    register('--remote-store-thread-count', type=int, advanced=True,
             default=DEFAULT_EXECUTION_OPTIONS.remote_store_thread_count,
             help='Thread count to use for the pool that interacts with the remote file store.')
    register('--remote-execution-server', advanced=True,
             help='host:port of grpc server to use as remote execution scheduler.')
    register('--remote-store-chunk-bytes', type=int, advanced=True,
             default=DEFAULT_EXECUTION_OPTIONS.remote_store_chunk_bytes,
             help='Size in bytes of chunks transferred to/from the remote file store.')
    register('--remote-store-chunk-upload-timeout-seconds', type=int, advanced=True,
             default=DEFAULT_EXECUTION_OPTIONS.remote_store_chunk_upload_timeout_seconds,
             help='Timeout (in seconds) for uploads of individual chunks to the remote file store.')
    register('--remote-instance-name', advanced=True,
             help='Name of the remote execution instance to use. Used for routing within '
                  '--remote-execution-server and --remote-store-server.')
    register('--remote-ca-certs-path', advanced=True,
             help='Path to a PEM file containing CA certificates used for verifying secure '
                  'connections to --remote-execution-server and --remote-store-server. '
                  'If not specified, TLS will not be used.')
    register('--remote-oauth-bearer-token-path', advanced=True,
             help='Path to a file containing an oauth token to use for grpc connections to '
                  '--remote-execution-server and --remote-store-server. If not specified, no '
                  'authorization will be performed.')

    # This should eventually deprecate the RunTracker worker count, which is used for legacy cache
    # lookups via CacheSetup in TaskBase.
    register('--process-execution-parallelism', type=int, default=multiprocessing.cpu_count(),
             advanced=True,
             help='Number of concurrent processes that may be executed either locally and remotely.')
    register('--process-execution-cleanup-local-dirs', type=bool, default=True, advanced=True,
             help='Whether or not to cleanup directories used for local process execution '
                  '(primarily useful for e.g. debugging).')

  @classmethod
  def register_options(cls, register):
    """Register options not tied to any particular task or subsystem."""
    # The bootstrap options need to be registered on the post-bootstrap Options instance, so it
    # won't choke on them on the command line, and also so we can access their values as regular
    # global-scope options, for convenience.
    cls.register_bootstrap_options(register)

    register('-x', '--time', type=bool,
             help='Output a timing report at the end of the run.')
    register('-e', '--explain', type=bool,
             help='Explain the execution of goals.')
    register('--tag', type=list, metavar='[+-]tag1,tag2,...',
             help="Include only targets with these tags (optional '+' prefix) or without these "
                  "tags ('-' prefix).  Useful with ::, to find subsets of targets "
                  "(e.g., integration tests.)")

    # Toggles v1/v2 `Task` vs `@rule` pipelines on/off.
    register('--v1', advanced=True, type=bool, default=True,
             help='Enables execution of v1 Tasks.')
    register('--v2', advanced=True, type=bool, default=False,
             help='Enables execution of v2 @console_rules.')
    register('--v2-ui', default=False, type=bool, daemon=False,
             help='Whether to show v2 engine execution progress. '
                  'This requires the --v2 flag to take effect.')

    loop_flag = '--loop'
    register(loop_flag, type=bool,
             help='Run v2 @console_rules continuously as file changes are detected. Requires '
                  '`--v2`, and is best utilized with `--v2 --no-v1`.')
    register('--loop-max', type=int, default=2**32, advanced=True,
             help='The maximum number of times to loop when `{}` is specified.'.format(loop_flag))

    register('-t', '--timeout', advanced=True, type=int, metavar='<seconds>',
             help='Number of seconds to wait for http connections.')
    # TODO: After moving to the new options system these abstraction leaks can go away.
    register('-k', '--kill-nailguns', advanced=True, type=bool,
             help='Kill nailguns before exiting')
    register('--fail-fast', advanced=True, type=bool, recursive=True,
             help='Exit as quickly as possible on error, rather than attempting to continue '
                  'to process the non-erroneous subset of the input.')
    register('--cache-key-gen-version', advanced=True, default='200', recursive=True,
             help='The cache key generation. Bump this to invalidate every artifact for a scope.')
    register('--workdir-max-build-entries', advanced=True, type=int, default=8,
             help='Maximum number of previous builds to keep per task target pair in workdir. '
             'If set, minimum 2 will always be kept to support incremental compilation.')
    register('--max-subprocess-args', advanced=True, type=int, default=100, recursive=True,
             help='Used to limit the number of arguments passed to some subprocesses by breaking '
             'the command up into multiple invocations.')
    register('--lock', advanced=True, type=bool, default=True,
             help='Use a global lock to exclude other versions of pants from running during '
                  'critical operations.')

  @classmethod
  def validate_instance(cls, opts):
    """Validates an instance of global options for cases that are not prohibited via registration.

    For example: mutually exclusive options may be registered by passing a `mutually_exclusive_group`,
    but when multiple flags must be specified together, it can be necessary to specify post-parse
    checks.

    Raises pants.option.errors.OptionsError on validation failure.
    """
    if opts.loop and (not opts.v2 or opts.v1):
      raise OptionsError('The --loop option only works with @console_rules, and thus requires '
                         '`--v2 --no-v1` to function as expected.')
    if opts.loop and not opts.enable_pantsd:
      raise OptionsError('The --loop option requires `--enable-pantsd`, in order to watch files.')

    if opts.v2_ui and not opts.v2:
      raise OptionsError('The --v2-ui option requires --v2 to be enabled together.')
