# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from builtins import str

from future.utils import binary_type

from pants.backend.native.config.environment import Platform
from pants.backend.native.subsystems.native_toolchain import GCCCToolchain, NativeToolchain
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.fs import Digest, MergedDirectories, Snapshot, rooted_toplevel_globs_for_paths
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Params
from pants.option.compiler_option_sets_mixin import CompilerOptionSetsMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.meta import classproperty
from pants.util.objects import datatype, string_list, string_type
from pants.util.strutil import safe_shlex_join, safe_shlex_split


logger = logging.getLogger(__name__)


class GraalCEUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://github.com/oracle/graal/releases/download/vm-{version}/{base}'
  _ARCHIVE_BASE_FMT = 'graalvm-ce-{version}-{system_id}-amd64.tar.gz'
  _SYSTEM_ID = {
    'mac': 'macos',
    'linux': 'linux',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    archive_basename = self._ARCHIVE_BASE_FMT.format(version=version, system_id=system_id)
    return [self._DIST_URL_FMT.format(version=version, base=archive_basename)]


class GraalCE(NativeTool):

  options_scope = 'graal'
  default_version = '1.0.0-rc15'
  archive_type = 'tgz'

  def get_external_url_generator(self):
    return GraalCEUrlGenerator()

  @classmethod
  def subsystem_dependencies(cls):
    return super(GraalCE, cls).subsystem_dependencies() + (
      NativeToolchain.scoped(cls),
    )

  @memoized_method
  def select(self, context=None):
    unpacked_base_path = super(GraalCE, self).select(context=context)
    trailing_containing_dirs = Platform.current.resolve_for_enum_variant({
      'darwin': ['Contents', 'home'],
      'linux': [],
    })
    return os.path.join(
      unpacked_base_path,
      'graalvm-ce-{}'.format(self.version()),
      *trailing_containing_dirs)

  @memoized_method
  def create_native_image_build_environment(self, context):
    gcc_c_toolchain, = context._scheduler.product_request(GCCCToolchain, tuple([
      Params(Platform.current, NativeToolchain.scoped_instance(self)),
    ]))
    gcc_c_compiler = gcc_c_toolchain.c_toolchain.c_compiler
    c_compiler_rooted_globs = rooted_toplevel_globs_for_paths(
      gcc_c_compiler.path_entries
      + gcc_c_compiler.runtime_library_dirs
      + gcc_c_compiler.include_dirs
    )

    # TODO(#7127): make @memoized_method convert lists to tuples for hashing!
    merged_snapshot = context._scheduler.capture_merged_snapshot(tuple(c_compiler_rooted_globs + [
      self._as_rooted_glob(context)
    ]))
    native_image_exe_path = os.path.realpath(os.path.join(self.select(), 'bin', 'native-image'))
    return NativeImageBuildEnvironment(
      merged_directories=merged_snapshot.directory_digest,
      # TODO: assert this is found as one of the .files in the merged snapshot?!
      native_image_tool_relpath=os.path.relpath(native_image_exe_path, self.select()),
    )


class BuildNativeImage(Subsystem, CompilerOptionSetsMixin):

  options_scope = 'build-native-image'

  @classmethod
  def register_options(cls, register):
    super(BuildNativeImage, cls).register_options(register)
    cls.register_compiler_option_sets_options(register)

    register('--max-heap-size', advanced=True,
             default='4g',
             help='The -Xmx argument provided to the native-image tool as it builds. '
                  'This value overrides any -Xmx value provided to in other jvm options.')
    register('--options', type=list, member_type=str,
             fingerprint=True, default=cls._default_cmdline_args,
             help='Arguments that are always passed to the native-image command line.')
    register('--compiler-option-sets', type=list, member_type=str,
             fingerprint=True, default=[],
             help='The "compiler_option_sets" value for building native images of this jvm tool.')

  @classproperty
  def get_compiler_option_sets_enabled_default_value(cls):
    return {
      'image-build-debug': [
        '--verbose',
        '--no-server',
        '-H:+ReportExceptionStackTraces',
      ],
      'release': ['-O9'],
    }

  @classproperty
  def get_compiler_option_sets_disabled_default_value(cls):
    return {
      'release': ['-O0'],
    }

  @classproperty
  def _default_cmdline_args(cls):
    return [
      '--enable-all-security-services',
      '--allow-incomplete-classpath',
      '--report-unsupported-elements-at-runtime',
    ]

  def generate_native_image_build_argv(self, tool_classpath, main_class, extra_args, exe_relpath,
                                       output_file_name):
    shlexed_options = [
      opt
      for el in self.get_options().options
      for opt in safe_shlex_split(el)
    ]

    merged_option_sets = self.get_merged_args_for_compiler_option_sets(
      self.get_options().compiler_option_sets)

    return (
      [
        exe_relpath,
        '-classpath', os.pathsep.join(tool_classpath),
        main_class,
        '-H:Name={}'.format(output_file_name),
        '-J-Xmx{}'.format(self.get_options().max_heap_size),
      ]
      + shlexed_options
      + merged_option_sets
      + list(extra_args))


class NativeImageBuildRequest(datatype([
    ('tool_classpath_snapshot', Snapshot),
    ('main_class', string_type),
    ('extra_args', string_list),
])):
  """Any configuration that needs to be provided to native-image to successfully build.

  While many jvm tools work out of the box with native-image, some require additional configuration
  to build correctly. Moreover, some may build correctly, but experience failures at runtime: see
  https://medium.com/graalvm/understanding-class-initialization-in-graalvm-native-image-generation-d765b7e4d6ed.

  More complex configuration such as substitutions can be embedded in the jar itself as in
  https://github.com/pantsbuild/pants/pull/7506, but that requires the tool's maintainer to have
  published jars with this configuration.

  For tools which don't work out of the box and haven't made changes upstream to support
  native-image, we can still use them in pants by providing an instance of this class to produce the
  necessary configuration.
  """

  def __new__(cls, tool_classpath_snapshot, main_class, extra_args=None):
    return super(NativeImageBuildRequest, cls).__new__(cls, tool_classpath_snapshot, main_class,
                                                       extra_args=extra_args or [])


class NativeImageBuildEnvironment(datatype([
    ('merged_directories', Digest),
    ('native_image_tool_relpath', string_type),
    # TODO: gcc relpath?!
])): pass


class CompiledNativeImage(datatype([
    ('file_path', string_type),
    ('built_image', Digest),
    ('stdout', binary_type),
    ('stderr', binary_type),
])): pass


@rule(CompiledNativeImage, [
  Platform,
  BuildNativeImage,
  NativeImageBuildEnvironment,
  NativeImageBuildRequest,
])
def build_native_image(platform, build_native_image, native_image_build_env, native_image_config):
  graal_digest = native_image_build_env.merged_directories
  native_image_tool_relpath = native_image_build_env.native_image_tool_relpath

  tool_classpath_snapshot = native_image_config.tool_classpath_snapshot
  main_class = native_image_config.main_class
  extra_args = native_image_config.extra_args

  image_output_file_name = '{}-pants-native-image'.format(main_class)

  all_digests = yield Get(
    Digest,
    MergedDirectories(directories=tuple([
      graal_digest,
      tool_classpath_snapshot.directory_digest,
    ]))
  )

  argv = build_native_image.generate_native_image_build_argv(
    tool_classpath_snapshot.files, main_class, extra_args, native_image_tool_relpath,
    image_output_file_name)

  sub_commands = []
  if platform == Platform.darwin:
    # native-image will specifically #include <CoreFoundation/CoreFoundation.h>
    # and we want to support that convention, so this uses a top-level 'Headers/' dir populated by
    # XCodeCLITools, and symlinks it to the desired 'CoreFoundation/' include directory.
    sub_commands.append('/bin/ln -sfv ../Headers include/CoreFoundation')
  sub_commands.append('PATH=$(pwd)/bin CPATH=$(pwd)/include {}'.format(safe_shlex_join(argv)))

  result = yield Get(ExecuteProcessResult, ExecuteProcessRequest(
    argv=tuple([
      '/bin/sh', '-c',
      ' && '.join(sub_commands),
    ]),
    input_files=all_digests,
    description='build native-image for {}'.format(main_class),
    output_files=tuple([image_output_file_name]),
  ))

  yield CompiledNativeImage(
    file_path=image_output_file_name,
    built_image=result.output_directory_digest,
    stdout=result.stdout,
    stderr=result.stderr,
  )


def rules():
  return [
    RootRule(BuildNativeImage),
    RootRule(NativeImageBuildEnvironment),
    RootRule(NativeImageBuildRequest),
    build_native_image
  ]
