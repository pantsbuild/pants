# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import copy
import os
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.build_graph.address import Address
from pants.util.dirutil import safe_mkdir
from pants_test.task_test_base import TaskTestBase

from pants.contrib.rust.targets.synthetic.cargo_synthetic_binary import CargoSyntheticBinary
from pants.contrib.rust.targets.synthetic.cargo_synthetic_custom_build import \
  CargoSyntheticCustomBuild
from pants.contrib.rust.tasks.cargo_build import Build


class CargoTaskBuild(TaskTestBase):
  @classmethod
  def task_type(cls):
    return Build

  def get_test_invocation(self, name, dependencies, toolchain, build_script=False):
    test_cargo_invocation = {
      'package_name': 'sha2',
      'package_version': '0.8.0',
      'target_kind': [
        'lib'
      ],
      'kind': 'Host',
      'compile_mode': 'build',
      'deps': dependencies,
      'outputs': [
        '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps/libsha2-f6245ef4e796fdb5.rlib'.format(
          name=name)
      ],
      'links': {
        '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/deps/libsha2-f6245ef4e796fdb5.rlib'.format(
          name=name): '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps/libsha2-f6245ef4e796fdb5.rlib'.format(
          name=name)
      },
      'program': 'rustc',
      'args': [
        '--crate-name',
        'sha2',
        '/root/.cargo/registry/src/github.com-1ecc6299db9ec823/sha2-0.8.0/src/lib.rs',
        '--color',
        'always',
        '--crate-type',
        'lib',
        '--emit=dep-info,link',
        '-C',
        'debuginfo=2',
        '--cfg',
        'feature=\'default\'',
        '--cfg',
        'feature=\'digest\'',
        '--cfg',
        'feature=\'std\'',
        '-C',
        'metadata=f6245ef4e796fdb5',
        '-C',
        'extra-filename=-f6245ef4e796fdb5',
        '--out-dir',
        '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps'.format(
          name=name),
        '-L',
        'dependency=/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps'.format(
          name=name),
        '--extern',
        'block_buffer=/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps/libblock_buffer-8efff75dcbc10d83.rlib'.format(
          name=name),
        '--extern',
        'digest=/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps/libdigest-5f1979ef5447de73.rlib'.format(
          name=name),
        '--extern',
        'fake_simd=/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps/libfake_simd-536d6e5b583fc52f.rlib'.format(
          name=name),
        '--extern',
        'opaque_debug=/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps/libopaque_debug-c6619a193d9a2c0c.rlib'.format(
          name=name),
        '--cap-lints',
        'allow'
      ],
      'env': {
        'CARGO': '/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/bin/cargo',
        'CARGO_MANIFEST_DIR': '/root/.cargo/registry/src/github.com-1ecc6299db9ec823/sha2-0.8.0',
        'CARGO_PKG_AUTHORS': 'RustCrypto Developers',
        'CARGO_PKG_DESCRIPTION': 'SHA-2 hash functions',
        'CARGO_PKG_HOMEPAGE': '',
        'CARGO_PKG_NAME': 'sha2',
        'CARGO_PKG_REPOSITORY': 'https://github.com/RustCrypto/hashes',
        'CARGO_PKG_VERSION': '0.8.0',
        'CARGO_PKG_VERSION_MAJOR': '0',
        'CARGO_PKG_VERSION_MINOR': '8',
        'CARGO_PKG_VERSION_PATCH': '0',
        'CARGO_PKG_VERSION_PRE': '',
        'OUT_DIR': '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/build/output'.format(
          name=name)
      },
      'cwd': os.path.join('root/.cargo/registry/src/github.com-1ecc6299db9ec823/sha2-0.8.0')
    }

    if toolchain == 'nightly_linux':
      test_cargo_invocation['env'].update({
        'LD_LIBRARY_PATH': '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/lib:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/lib'.format(
          name=name)})
    elif toolchain == 'nightly_2018_12_31_macos':
      test_cargo_invocation['env'].update({
        'DYLD_LIBRARY_PATH': '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/lib:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/lib'.format(
          name=name)}),
    elif toolchain == 'nightly_macos':
      test_cargo_invocation['env'].update({
        'DYLD_FALLBACK_LIBRARY_PATH': '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/deps:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/lib:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/lib'.format(
          name=name)}),

    if build_script:
      test_cargo_invocation[
        'program'] = '/test_pants/contrib/rust/examples/src/rust/lib_kinds/{name}/target/debug/build/byteorder-bf549d3401bc1e38/build-script-build'.format(
        name=name)
      test_cargo_invocation['compile_mode'] = 'run-custom-build'

    return copy.deepcopy(test_cargo_invocation)

  def get_cargo_statements(self):
    return {
      'rustc-flags': [
        [
          '-l',
          'static=samplerate'
        ],
        [
          '-l',
          'dylib=stdc++'
        ],
        [
          '-l',
          'static=pfring',
          '-L',
          '/usr/local/lib'
        ],
        [
          '-l',
          'static=pcap',
          '-L',
          '/usr/local/lib'
        ],
      ],
      'rustc-env': [
        [
          'PROTOC',
          '/protobuf/protoc'
        ],
        [
          'PROTOC_INCLUDE',
          '/protobuf/include'
        ]
      ],
      'rustc-link-search': [
        [
          '-L',
          'native=pants/.pants.d/engine/out'
        ],
      ],
      'rustc-link-lib': [
        [
          '-l',
          'static=native_engine_ffi'
        ],
      ],
      'rustc-cfg': [
        [
          '--cfg',
          'rust_1_26'
        ],
        [
          '--cfg',
          'memchr_runtime_sse42'
        ]
      ],
      'warning': [
        '/lmdb-sys/lmdb/libraries/liblmdb/mdb.c:10033:33: warning: unused parameter [-Wunused-parameter]',
        'mdb_env_get_maxkeysize(MDB_env *env)',
        '                                ^',
        '1 warning generated.'
      ],
      'rerun-if-env-changed': [
        'PY'
      ],
      'rerun-if-changed': [
        'cbindgen.toml'
      ]
    }

  def test_get_build_flags(self):
    context = self.context(options={'test_scope': {'cargo_opt': ['--a', '--c', '--b']}})
    task = self.create_task(context)

    context.products.safe_create_data('cargo_toolchain', lambda: 'nightly-xyz')

    flags = task.get_build_flags()
    self.assertEqual('--a --b --c nightly-xyz', flags)

  def test_get_build_flags_without_options(self):
    context = self.context()
    task = self.create_task(context)

    context.products.safe_create_data('cargo_toolchain', lambda: 'nightly-xyz')

    flags = task.get_build_flags()
    self.assertEqual('nightly-xyz', flags)

  def test_get_build_flags_with_include_tests(self):
    context = self.context(options={'test_scope': {'cargo_opt': ['--a', '--c', '--b']}})
    task = self.create_task(context)

    context.products.safe_create_data('cargo_toolchain', lambda: 'nightly-xyz')
    context.products.require_data('rust_tests')

    flags = task.get_build_flags()
    self.assertEqual('--a --b --c nightly-xyz --tests', flags)

  def test_create_libraries_dir(self):
    task = self.create_task(self.context())
    libraries_dir = os.path.join(task.versioned_workdir, 'deps')

    task.create_libraries_dir()

    self.assertTrue(os.path.isdir(libraries_dir))

  def test_create_build_index_dir(self):
    task = self.create_task(self.context())
    build_index_dir = os.path.join(task.versioned_workdir, 'build_index')

    task.create_build_index_dir()

    self.assertTrue(os.path.isdir(build_index_dir))

  def test_include_compiling_tests_true(self):
    context = self.context()
    task = self.create_task(context)
    context.products.require_data('rust_tests')

    self.assertTrue(task.include_compiling_tests())

  def test_include_compiling_tests_false(self):
    task = self.create_task(self.context())

    self.assertFalse(task.include_compiling_tests())

  def test_parse_build_script_output(self):
    build_output = dedent("""
      cargo:rustc-link-lib=static=native_engine_ffi
      cargo:rustc-link-search=native=pants/.pants.d/engine/out
      warning=1 warning generated.
      cargo:rustc-cfg=rust_1_26
      warning=/lmdb-sys/lmdb/libraries/liblmdb/mdb.c:10033:33: warning: unused parameter [-Wunused-parameter]
      warning=mdb_env_get_maxkeysize(MDB_env *env)
      warning=                                ^
      warning=1 warning generated.
    """)

    task = self.create_task(self.context())
    cargo_statements = task.parse_build_script_output(build_output)

    expect = ['cargo:rustc-link-lib=static=native_engine_ffi',
              'cargo:rustc-link-search=native=pants/.pants.d/engine/out',
              'cargo:rustc-cfg=rust_1_26']

    self.assertEqual(expect, cargo_statements)

  def test_create_build_script_output_path(self):
    task = self.create_task(self.context())
    output_path = '/Users/Home/pants/.pants.d/compile/cargo/e8acf1b202cf/lib_1/current/build/lib_1/out'

    result = task.create_build_script_output_path(output_path)
    expect = '/Users/Home/pants/.pants.d/compile/cargo/e8acf1b202cf/lib_1/current/build/lib_1/output'
    self.assertEqual(expect, result)

  def test_create_build_script_stderr_path(self):
    task = self.create_task(self.context())
    output_path = '/Users/Home/pants/.pants.d/compile/cargo/e8acf1b202cf/lib_1/current/build/lib_1/out'

    result = task.create_build_script_stderr_path(output_path)
    expect = '/Users/Home/pants/.pants.d/compile/cargo/e8acf1b202cf/lib_1/current/build/lib_1/stderr'
    self.assertEqual(expect, result)

  def test_create_directories(self):
    task = self.create_task(self.context())

    dir_1 = os.path.join(get_buildroot(),
                         'pants/.pants.d/compile/cargo/e8acf1b202cf/lib_1/current/build')
    dir_2 = os.path.join(get_buildroot(),
                         'pants/.pants.d/compile/cargo/e8acf1b202cf/lib_1/current/incremental')
    mkdir = {dir_1, dir_2}

    self.assertListEqual([False] * len(mkdir), list(map(lambda dir: os.path.isdir(dir), mkdir)))

    task.create_directories(mkdir)

    self.assertListEqual([True] * len(mkdir), list(map(lambda dir: os.path.isdir(dir), mkdir)))

  def test_create_library_symlink(self):
    task = self.create_task(self.context())

    dir_1 = os.path.join(task.versioned_workdir, 'lib_1/current')
    dir_2 = os.path.join(task.versioned_workdir, 'lib_2/current')
    mkdir = {dir_1, dir_2}

    for dir in mkdir:
      safe_mkdir(dir)

    lib_1 = os.path.join(dir_1, 'lib_1.xyz')
    lib_2 = os.path.join(dir_1, 'lib_2.xyz')

    mklib = {lib_1, lib_2}
    for lib in mklib:
      self.create_file(lib, contents="")

    libraries_dir = os.path.join(task.versioned_workdir, 'deps')
    safe_mkdir(libraries_dir)

    lib_1_sym = os.path.join(libraries_dir, 'lib_1.xyz')
    lib_2_sym = os.path.join(libraries_dir, 'lib_2.xyz')

    lib_sym = {lib_1_sym, lib_2_sym}

    self.assertListEqual([False] * len(lib_sym),
                         list(map(lambda dir: os.path.exists(dir), lib_sym)))

    task.create_library_symlink(mklib, libraries_dir)

    self.assertListEqual([True] * len(lib_sym), list(map(lambda dir: os.path.islink(dir), lib_sym)))

  def test_create_copies(self):
    task = self.create_task(self.context())

    dir_1 = os.path.join(task.versioned_workdir, 'lib_1/current')
    dir_1_1 = os.path.join(task.versioned_workdir, 'lib_1/current/deps')
    dir_1_1_1 = os.path.join(task.versioned_workdir, 'lib_1/current/deps/lib_1')
    dir_2 = os.path.join(task.versioned_workdir, 'lib_2/current')
    dir_2_1 = os.path.join(task.versioned_workdir, 'lib_2/current/deps')
    dir_2_1_1 = os.path.join(task.versioned_workdir, 'lib_2/current/deps/lib_2')
    mkdir = {dir_1_1_1, dir_2_1}

    for dir in mkdir:
      safe_mkdir(dir)

    lib_1 = os.path.join(dir_1_1, 'lib_1.dylib')
    lib_1_dir = os.path.join(dir_1_1_1, 'lib_1.dylib')
    lib_2 = os.path.join(dir_2_1, 'lib_2.dylib')

    mklib = {lib_1, lib_1_dir}
    for lib in mklib:
      self.create_file(lib, contents="")

    links = {os.path.join(dir_1, 'lib_1.dylib'): lib_1,
             os.path.join(dir_1, 'lib_1'): dir_1_1_1,
             os.path.join(dir_2, 'lib_2.dylib'): lib_2,
             os.path.join(dir_2, 'lib_2'): dir_2_1_1, }

    self.assertFalse(os.path.exists(os.path.join(dir_1, 'lib_1.dylib')))
    self.assertFalse(os.path.exists(os.path.join(dir_1, 'lib_1')))
    self.assertFalse(os.path.exists(os.path.join(dir_2, 'lib_2.dylib')))
    self.assertFalse(os.path.exists(os.path.join(dir_2, 'lib_2')))

    task.create_copies(links)

    self.assertTrue(os.path.isfile(os.path.join(dir_1, 'lib_1.dylib')))
    self.assertTrue(os.path.isdir(os.path.join(dir_1, 'lib_1')))
    self.assertTrue(os.path.isfile(os.path.join(dir_1, 'lib_1/lib_1.dylib')))
    self.assertFalse(os.path.exists(os.path.join(dir_2, 'lib_2.dylib')))
    self.assertFalse(os.path.exists(os.path.join(dir_2, 'lib_2')))

  def test_get_build_index_file_path(self):
    task = self.create_task(self.context())
    build_index_dir = os.path.join(task.versioned_workdir, 'build_index')
    task._build_index_dir_path = build_index_dir
    build_index_file_path = os.path.join(build_index_dir, 'index.json')

    self.assertEqual(build_index_file_path, task.get_build_index_file_path())

  def test_calculate_target_definition_fingerprint_mode_build_nightly_2018_12_31_macos(self):
    build_invocation_target_1 = self.get_test_invocation('cdylib', [2, 4, 5],
                                                         'nightly_2018_12_31_macos')
    build_invocation_target_2 = self.get_test_invocation('dylib', [1, 2, 3],
                                                         'nightly_2018_12_31_macos')

    task = self.create_task(self.context())
    self.assertEqual(task.calculate_target_definition_fingerprint(build_invocation_target_1),
                     task.calculate_target_definition_fingerprint(build_invocation_target_2))

  def test_calculate_target_definition_fingerprint_mode_build_nightly_macos(self):
    build_invocation_target_1 = self.get_test_invocation('cdylib', [2, 4, 5], 'nightly_macos')
    build_invocation_target_2 = self.get_test_invocation('dylib', [1, 2, 3], 'nightly_macos')

    task = self.create_task(self.context())
    self.assertEqual(task.calculate_target_definition_fingerprint(build_invocation_target_1),
                     task.calculate_target_definition_fingerprint(build_invocation_target_2))

  def test_calculate_target_definition_fingerprint_mode_build_nightly_linux(self):
    build_invocation_target_1 = self.get_test_invocation('cdylib', [2, 4, 5], 'nightly_linux')
    build_invocation_target_2 = self.get_test_invocation('dylib', [1, 2, 3], 'nightly_linux')

    task = self.create_task(self.context())
    self.assertEqual(task.calculate_target_definition_fingerprint(build_invocation_target_1),
                     task.calculate_target_definition_fingerprint(build_invocation_target_2))

  def test_calculate_target_definition_fingerprint_mode_run_custom_build(self):
    build_invocation_target_1 = self.get_test_invocation('cdylib', [2, 4, 5],
                                                         'nightly_2018_12_31_macos',
                                                         build_script=True)
    build_invocation_target_2 = self.get_test_invocation('dylib', [1, 2, 3],
                                                         'nightly_2018_12_31_macos',
                                                         build_script=True)

    task = self.create_task(self.context())
    self.assertEqual(task.calculate_target_definition_fingerprint(build_invocation_target_1),
                     task.calculate_target_definition_fingerprint(build_invocation_target_2))

  def test_save_and_parse_build_script_output(self):
    task = self.create_task(self.context())

    t1 = self.make_target(spec='test', cargo_invocation={}, target_type=CargoSyntheticCustomBuild)

    build_output = dedent("""
      cargo:rustc-link-lib=static=native_engine_ffi
      cargo:rustc-link-search=native=pants/.pants.d/engine/out
      warning=1 warning generated.
      cargo:rustc-cfg=rust_1_26
      warning=/lmdb-sys/lmdb/libraries/liblmdb/mdb.c:10033:33: warning: unused parameter [-Wunused-parameter]
      warning=mdb_env_get_maxkeysize(MDB_env *env)
      warning=                                ^
      warning=1 warning generated.
    """)

    out_dir = os.path.join(task.versioned_workdir, 'test/current/build/lib_1/out')

    cargo_statements = task.save_and_parse_build_script_output(build_output, out_dir, t1)
    result = {
      'rustc-flags': [],
      'rustc-env': [],
      'rustc-link-search': [
        [
          '-L',
          'native=pants/.pants.d/engine/out'
        ],
      ],
      'rustc-link-lib': [
        [
          '-l',
          'static=native_engine_ffi'
        ],
      ],
      'rustc-cfg': [
        [
          '--cfg',
          'rust_1_26'
        ]
      ],
      'warning': [],
      'rerun-if-changed': [],
      'rerun-if-env-changed': []
    }
    self.assertTrue(
      os.path.isfile(os.path.join(task.versioned_workdir, 'test/current/build/lib_1/output')))
    self.assertEqual(result, cargo_statements)

  def test_extend_args_with_cargo_statement_without_build_script(self):
    task = self.create_task(self.context())

    t1 = self.make_target(spec='test', cargo_invocation={}, target_type=CargoSyntheticBinary)

    cmd = ['rustc', '--crate-name', 'test', '--release']

    extend_cmd = task.extend_args_with_cargo_statement(cmd, t1)

    self.assertEqual(cmd, extend_cmd)

  def test_extend_args_with_cargo_statement_with_build_script(self):
    task = self.create_task(self.context())

    t1 = self.make_target(spec='test', cargo_invocation={}, target_type=CargoSyntheticCustomBuild)
    t2 = self.make_target(spec='test_2', cargo_invocation={}, target_type=CargoSyntheticBinary,
                          dependencies=[t1])

    task._build_script_output_cache['test'] = self.get_cargo_statements()

    cmd = ['rustc', '--crate-name', 'test', '--release']

    extend_cmd = task.extend_args_with_cargo_statement(cmd, t2)

    result = ['rustc', '--crate-name', 'test', '--release',
              '-l',
              'static=native_engine_ffi',
              '-L',
              'native=pants/.pants.d/engine/out',
              '-l',
              'static=samplerate',
              '-l',
              'dylib=stdc++',
              '-l',
              'static=pfring',
              '-L',
              '/usr/local/lib',
              '-l',
              'static=pcap',
              '-L',
              '/usr/local/lib',
              '--cfg',
              'rust_1_26',
              '--cfg',
              'memchr_runtime_sse42']

    self.assertEqual(result, extend_cmd)

  def test_create_command(self):
    task = self.create_task(self.context())
    t1 = self.make_target(spec='test', cargo_invocation={}, target_type=CargoSyntheticBinary)

    cmd = task.create_command('rustc', ['--crate-name', 'test', '--release'], t1)

    self.assertEqual(['rustc', '--crate-name', 'test', '--release'], cmd)

  def test_create_env(self):
    context = self.context()
    task = self.create_task(context)

    cargo_home = os.path.join(task.versioned_workdir, 'cargo_home')
    env = os.environ.copy()
    cargo_path = os.path.join(env['HOME'], '.cargo/bin')
    context.products.safe_create_data('cargo_env',
                                      lambda: {'CARGO_HOME': cargo_home, 'PATH': cargo_path})
    cargo_toolchain = 'nightly'
    context.products.safe_create_data('cargo_toolchain', lambda: cargo_toolchain)

    t1 = self.make_target(spec='test', cargo_invocation={}, target_type=CargoSyntheticCustomBuild)
    t2 = self.make_target(spec='test_2', cargo_invocation={}, target_type=CargoSyntheticBinary,
                          dependencies=[t1])

    task._build_script_output_cache['test'] = self.get_cargo_statements()

    invocation_env = {
      'CARGO': '/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/bin/cargo',
      'CARGO_MANIFEST_DIR': '/root/.cargo/registry/src/github.com-1ecc6299db9ec823/sha2-0.8.0',
      'CARGO_PKG_AUTHORS': 'RustCrypto Developers',
      'CARGO_PKG_DESCRIPTION': 'SHA-2 hash functions',
      'CARGO_PKG_HOMEPAGE': '',
      'CARGO_PKG_NAME': 'sha2',
      'CARGO_PKG_REPOSITORY': 'https://github.com/RustCrypto/hashes',
      'CARGO_PKG_VERSION': '0.8.0',
      'CARGO_PKG_VERSION_MAJOR': '0',
      'CARGO_PKG_VERSION_MINOR': '8',
      'CARGO_PKG_VERSION_PATCH': '0',
      'CARGO_PKG_VERSION_PRE': ''
    }

    target_env = task.create_env(invocation_env, t2)

    result = {
      'CARGO': (
        '/root/.rustup/toolchains/nightly-2018-12-31-x86_64-unknown-linux-gnu/bin/cargo', False),
      'CARGO_MANIFEST_DIR': (
        '/root/.cargo/registry/src/github.com-1ecc6299db9ec823/sha2-0.8.0', False),
      'CARGO_PKG_AUTHORS': ('RustCrypto Developers', False),
      'CARGO_PKG_DESCRIPTION': ('SHA-2 hash functions', False),
      'CARGO_PKG_HOMEPAGE': ('', False),
      'CARGO_PKG_NAME': ('sha2', False),
      'CARGO_PKG_REPOSITORY': ('https://github.com/RustCrypto/hashes', False),
      'CARGO_PKG_VERSION': ('0.8.0', False),
      'CARGO_PKG_VERSION_MAJOR': ('0', False),
      'CARGO_PKG_VERSION_MINOR': ('8', False),
      'CARGO_PKG_VERSION_PATCH': ('0', False),
      'CARGO_PKG_VERSION_PRE': ('', False),
      'PATH': (cargo_path, True),
      'RUSTUP_TOOLCHAIN': (cargo_toolchain, False),
      'PROTOC': ('/protobuf/protoc', False),
      'PROTOC_INCLUDE': ('/protobuf/include', False)
    }

    self.assertEqual(result, target_env)

  def test_extend_env_with_cargo_statement_without_cargo_statements(self):
    task = self.create_task(self.context())

    t1 = self.make_target(spec='test', cargo_invocation={}, target_type=CargoSyntheticBinary)

    extend_env = task.extend_env_with_cargo_statement({}, t1)

    self.assertEqual({}, extend_env)

  def test_extend_env_with_cargo_statement_with_cargo_statements(self):
    task = self.create_task(self.context())

    t1 = self.make_target(spec='test', cargo_invocation={}, target_type=CargoSyntheticCustomBuild)
    t2 = self.make_target(spec='test_2', cargo_invocation={}, target_type=CargoSyntheticBinary,
                          dependencies=[t1])

    task._build_script_output_cache['test'] = self.get_cargo_statements()

    extend_env = task.extend_env_with_cargo_statement({}, t2)

    result = {'PROTOC': ('/protobuf/protoc', False),
              'PROTOC_INCLUDE': ('/protobuf/include', False)}

    self.assertEqual(result, extend_env)

  def test_create_target_definition(self):
    TargetDefinition = collections.namedtuple('TargetDefinition',
                                              'name, id, address, '
                                              'dependencies, kind, '
                                              'invocation, compile_mode')

    task = self.create_task(self.context())
    cargo_invocation = self.get_test_invocation('test', [3], 'nightly_linux')
    cwd = os.path.join(get_buildroot(), 'test')
    cargo_invocation['cwd'] = cwd

    copy_cargo_invocation = self.get_test_invocation('test', [3], 'nightly_linux')
    copy_cargo_invocation['cwd'] = cwd
    copy_cargo_invocation.pop('deps')

    fingerprint = 'sha2_{0}'.format(task.calculate_target_definition_fingerprint(cargo_invocation))
    result = TargetDefinition('sha2', fingerprint,
                              Address(os.path.relpath(cwd, get_buildroot()), fingerprint), [3],
                              'lib', copy_cargo_invocation, 'build')

    td = task.create_target_definition(cargo_invocation)
    self.assertEqual(result, td)

# def prepare_task(self):
# def prepare_cargo_targets(self):
# def get_cargo_build_plan(self, target):
# def get_target_definitions_out_of_cargo_build_plan(self, cargo_build_plan):
# def generate_targets(self, target_definitions, cargo_target):
# def is_lib_or_bin(self, target_definition, original_target):
# def inject_lib_or_bin_target(self, target_definition, original_target):
# def build_targets(self, targets):
# def convert_cargo_invocation_into_pants_invocation(self, vt):
# def build_target(self, target, pants_invocation):
# def execute_custom_build(self, cmd, workunit_name, env, cwd, target):
# def execute_rustc(self, package_name, cmd, workunit_name, env, cwd):
# def add_rust_products(self, target, pants_invocation):
# def mark_target_invalid(self, address):
# def check_if_build_scripts_are_invalid(self):
# def read_build_index(self):
# def write_build_index(self):
