# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import str

from future.utils import text_type

from pants.backend.cargo_bootstrap.subsystems.cmake_for_grpc import CMakeForGRPC
from pants.backend.cargo_bootstrap.subsystems.go_for_grpc import GoForGRPC
from pants.backend.cargo_bootstrap.subsystems.protoc_for_grpc import ProtocForGRPC
from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.base.hash_utils import stable_json_hash
from pants.binaries.binary_tool import Script
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.fs import PathGlobs, PathGlobsAndRoot, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.net.http.fetcher import Fetcher
from pants.option.custom_types import list_option
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import environment_as
from pants.util.dirutil import chmod_plus_x, is_executable
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import subprocess
from pants.util.strutil import create_path_env_var


class RustupUrlGenerator(BinaryToolUrlGenerator):

  RUSTUP_SCRIPT_URL = 'https://sh.rustup.rs'

  def generate_urls(self, version, host_platform):
    return [self.RUSTUP_SCRIPT_URL]


class Rustup(Script):
  options_scope = 'rustup'
  name = 'rustup.sh'

  def get_external_url_generator(self):
    return RustupUrlGenerator()

  @classmethod
  def subsystem_dependencies(cls):
    return super(Rustup, cls).subsystem_dependencies() + (
      CMakeForGRPC.scoped(cls),
      GoForGRPC.scoped(cls),
      ProtocForGRPC.scoped(cls),
    )

  @classmethod
  def register_options(cls, register):
    super(Rustup, cls).register_options(register)
    register('--toolchain-version', type=str, default='1.30.0',
             help='???')
    register('--rust-components', type=list_option, default=[
      'rustfmt-preview',
      'rust-src',
      'clippy-preview',
    ], help='???')
    register('--cargo-version', type=str, default='0.2.1',
             help='???')

  @memoized_property
  def update_request(self):
    opts = self.get_options()
    version = opts.toolchain_version
    components = opts.rust_components
    return RustUpdateRequest(
      toolchain_root=self._toolchain_root,
      toolchain_version=version,
      rust_components=tuple(components),
    )

  @memoized_property
  def cargo_version(self):
    return self.get_options().cargo_version

  @memoized_property
  def _toolchain_root(self):
    return os.path.join(get_pants_cachedir(), 'rust')

  @memoized_property
  def _cargo_home(self):
    return os.path.join(self._toolchain_root, 'cargo')

  @memoized_property
  def _rustup_home(self):
    return os.path.join(self._toolchain_root, 'rustup')

  @memoized_property
  def _cargo_bin_dir(self):
    return os.path.join(self._cargo_home, 'bin')

  @memoized_property
  def pants_owned_rustup_path(self):
    return os.path.join(self._cargo_bin_dir, 'rustup')

  @memoized_property
  def pants_owned_rustup_globs(self):
    return PathGlobsAndRoot(PathGlobs(['rustup']), self._cargo_bin_dir)

  @memoized_property
  def cargo_ensure_installed_path(self):
    return os.path.join(self._cargo_bin_dir, 'cargo-ensure-installed')

  @memoized_property
  def cargo_ensure_installed_globs(self):
    return PathGlobsAndRoot(PathGlobs(['cargo-ensure-installed']), self._cargo_bin_dir)

  @memoized_property
  def _cmake(self):
    return CMakeForGRPC.scoped_instance(self)

  @memoized_property
  def _go_dist(self):
    return GoForGRPC.scoped_instance(self)

  @memoized_property
  def _protoc(self):
    return ProtocForGRPC.scoped_instance(self)

  @memoized_method
  def rustup_exec_env(self):
    return {
      'CARGO_HOME': self._cargo_home,
      'RUSTUP_HOME': self._rustup_home,
      'PATH': create_path_env_var([
        self._cmake.bin_dir(),
        self._go_dist.bin_dir(),
        self._protoc.bin_dir(),
      ]
      )
    }


class RustupExe(datatype([('exe', Snapshot)])): pass


@rule(RustupExe, [Select(Rustup)])
def unpack_rustup(rustup):
  if not is_executable(rustup.pants_owned_rustup_path):
    script = rustup.hackily_snapshot(context=None)
    req = ExecuteProcessRequest(
      argv=('./rustup.sh', '-y', '--no-modify-path', '--default-toolchain', 'none'),
      input_files=script.directory_digest,
      description='execute rustup',
      env=rustup.rustup_exec_env(),
    )
    # TODO: this isn't remotable -- it will modify the local filesystem at CARGO_HOME and
    # RUSTUP_HOME. Right now I can't figure out how to e.g. make temporary directories and fit that
    # into the process execution API.
    yield Get(ExecuteProcessResult, ExecuteProcessRequest, req)
    assert(is_executable(rustup.pants_owned_rustup_path))

  rustup_snapshot = yield Get(Snapshot, PathGlobsAndRoot, rustup.pants_owned_rustup_globs)
  yield RustupExe(rustup_snapshot)


class RustUpdateRequest(datatype([
    ('toolchain_root', text_type),
    ('toolchain_version', text_type),
    ('rust_components', tuple),
])):

  @memoized_property
  def cargo_fingerprinted_filename(self):
    return 'cargo-{}'.format(stable_json_hash(self))


class CargoBin(datatype([
    'bin_path',
    ('exe', Snapshot),
])): pass


@rule(CargoBin, [Select(Rustup), Select(RustupExe)])
def obtain_cargo_bin_location(rustup, rustup_exe):
  update_request = rustup.update_request

  cargo_versioned_path = os.path.join(
    update_request.toolchain_root,
    update_request.cargo_fingerprinted_filename,
  )

  which_cargo_env = rustup.rustup_exec_env().copy()
  which_cargo_env['RUSTUP_TOOLCHAIN'] = version

  which_cargo_req = ExecuteProcessRequest(
    argv=('./rustup', 'which', 'cargo'),
    input_files=rustup_exe.exe,
    description='get rustup cargo bin location',
    env=which_cargo_env,
  )
  which_cargo_res = yield Get(ExecuteProcessResult, ExecuteProcessRequest, which_cargo_req)
  cargo_bin_path = which_cargo_res.stdout.strip()
  symlink_target = os.path.relpath(cargo_bin_path, update_request.toolchain_root)

  cargo_bin_globs = PathGlobsAndRoot([symlink_target], update_request.toolchain_root)

  version = update_request.toolchain_version

  # If rustup was already bootstrapped against a different toolchain in the past, freshen it and
  # ensure the toolchain and components we need are installed.
  # TODO: mention what the "nightly" part does!
  if not is_executable(cargo_versioned_path) or version == 'nightly':
    def rustup_update_request(argv, sub_description):
      return ExecuteProcessRequest(
        argv=tuple(['./rustup'] + argv),
        input_files=rustup_exe.exe,
        description='freshen rust toolchain: {}'.format(sub_description),
        env=rustup.rustup_exec_env(),
      )

    components = update_request.rust_components

    yield Get(ExecuteProcessResult, ExecuteProcessRequest,
              rustup_update_request(['self', 'update'], 'update rustup'))
    yield Get(ExecuteProcessResult, ExecuteProcessRequest,
              rustup_update_request(['toolchain', 'install', version],
                                    "install toolchain '{}'".format(version)))
    yield Get(ExecuteProcessResult, ExecuteProcessRequest,
              rustup_update_request(['component', 'add', '--toolchain', version] + list(components),
                                    'add components {} to the toolchain'.format(components)))
    # NB: We don't use the symlink here, but we keep in the fs for backwards compat for now (see how
    # we check its existence above).
    if os.path.exists(cargo_versioned_path):
      os.unlink(cargo_versioned_path)
    os.symlink(symlink_target, cargo_versioned_path)
    assert(is_executable(cargo_versioned_path))

  cargo_exe = yield Get(Snapshot, PathGlobsAndRoot, cargo_bin_globs)
  yield CargoBin(cargo_bin_path, cargo_exe)


class CargoInstallation(datatype([
    ('cargo_bin', CargoBin),
    ('rustup', Rustup),
    'cargo_installed_version',
])):

  @memoized_method
  def cargo_exec_env(self):
    env = rustup.rustup_exec_env().copy()
    env['PATH'] = create_path_env_var([
      os.path.dirname(self.cargo_bin.bin_path),
    ], env=env, prepend=True)
    return env


@rule(CargoInstallation, [Select(Rustup), Select(CargoBin)])
def ensure_cargo_installed(rustup, cargo_bin):
  if not is_executable(rustup.cargo_ensure_installed_path):
    cargo_install_req = ExecuteProcessRequest(
      argv=('./cargo', 'install', 'cargo-ensure-installed'),
      input_files=cargo_bin.exe,
      description='install cargo-ensure-installed (???)',
      env=rustup_exec_env(),
    )
    # yield Get(ExecuteProcessResult, ExecuteProcessRequest, cargo_install_req)

  cargo_package_req = ExecuteProcessRequest(
    argv=('./cargo', 'ensure-installed',
          '--package', 'cargo-ensure-installed',
          '--version', rustup.cargo_version),
    input_files=cargo_bin.exe,
    description='run cargo-ensure-installed (???)',
    env=rustup_exec_env(),
  )
  yield Get(ExecuteProcessResult, ExecuteProcessRequest, cargo_package_req)

  yield CargoInstallation(cargo_bin, rustup, cargo_installed_version=rustup.cargo_version)


def rustup_rules():
  return [
    unpack_rustup,
    obtain_cargo_bin_location,
    ensure_cargo_installed,
    RootRule(Rustup),
  ]
