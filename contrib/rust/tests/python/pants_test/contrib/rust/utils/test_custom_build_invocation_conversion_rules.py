# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import copy
import unittest

from pants.contrib.rust.utils.custom_build_invocation_conversion_rules import (args_rules,
                                                                               env_rules,
                                                                               links_rules,
                                                                               outputs_rules,
                                                                               program_rules)


custom_build_invocation = {
  "package_name": "engine",
  "package_version": "0.0.1",
  "target_kind": [
    "custom-build"
  ],
  "kind": "Host",
  "compile_mode": "build",
  "outputs": [
    "/pants/src/rust/engine/target/debug/build/engine-0c8d5cf2130633dc/build_script_cffi_build-0c8d5cf2130633dc"
  ],
  "links": {
    "/pants/src/rust/engine/target/debug/build/engine-0c8d5cf2130633dc/build-script-cffi_build": "/pants/src/rust/engine/target/debug/build/engine-0c8d5cf2130633dc/build_script_cffi_build-0c8d5cf2130633dc"
  },
  "program": "rustc",
  "args": [
    "--edition=2018",
    "--crate-name",
    "build_script_cffi_build",
    "src/cffi_build.rs",
    "--color",
    "always",
    "--crate-type",
    "bin",
    "--emit=dep-info,link",
    "-C",
    "debuginfo=2",
    "-C",
    "metadata=0c8d5cf2130633dc",
    "-C",
    "extra-filename=-0c8d5cf2130633dc",
    "--out-dir",
    "/pants/src/rust/engine/target/debug/build/engine-0c8d5cf2130633dc",
    "-C",
    "incremental=/pants/src/rust/engine/target/debug/incremental",
    "-L",
    "dependency=/pants/src/rust/engine/target/debug/deps",
    "--extern",
    "build_utils=/pants/src/rust/engine/target/debug/deps/libbuild_utils-cb8514cd7dbe5a1c.rlib",
    "--extern",
    "cbindgen=/pants/src/rust/engine/target/debug/deps/libcbindgen-cdeba0a445e93ac7.rlib",
    "--extern",
    "cc=/pants/src/rust/engine/target/debug/deps/libcc-6d75c99c01814b55.rlib",
    "-C",
    "link-args=-undefined dynamic_lookup"
  ],
  "env": {
    "CARGO": "/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/bin/cargo",
    "CARGO_MANIFEST_DIR": "/pants/src/rust/engine",
    "CARGO_PKG_AUTHORS": "Pants Build <pantsbuild@gmail.com>",
    "CARGO_PKG_DESCRIPTION": "",
    "CARGO_PKG_HOMEPAGE": "",
    "CARGO_PKG_NAME": "engine",
    "CARGO_PKG_REPOSITORY": "",
    "CARGO_PKG_VERSION": "0.0.1",
    "CARGO_PKG_VERSION_MAJOR": "0",
    "CARGO_PKG_VERSION_MINOR": "0",
    "CARGO_PKG_VERSION_PATCH": "1",
    "CARGO_PKG_VERSION_PRE": "",
    "CARGO_PRIMARY_PACKAGE": "1",
    "DYLD_LIBRARY_PATH": "/pants/src/rust/engine/target/debug/deps:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib"
  },
  "cwd": "/pants/src/rust/engine"
}

run_custom_build_invocation = {
  "package_name": "engine",
  "package_version": "0.0.1",
  "target_kind": [
    "custom-build"
  ],
  "kind": "Host",
  "compile_mode": "run-custom-build",
  "outputs": [],
  "links": {},
  "program": "/pants/src/rust/engine/target/debug/build/engine-0c8d5cf2130633dc/build-script-cffi_build",
  "args": [],
  "env": {
    "CARGO": "/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/bin/cargo",
    "CARGO_CFG_DEBUG_ASSERTIONS": "",
    "CARGO_CFG_PROC_MACRO": "",
    "CARGO_CFG_TARGET_ARCH": "x86_64",
    "CARGO_CFG_TARGET_ENDIAN": "little",
    "CARGO_CFG_TARGET_ENV": "",
    "CARGO_CFG_TARGET_FAMILY": "unix",
    "CARGO_CFG_TARGET_FEATURE": "cmpxchg16b,fxsr,mmx,sse,sse2,sse3,ssse3",
    "CARGO_CFG_TARGET_HAS_ATOMIC": "128,16,32,64,8,cas,ptr",
    "CARGO_CFG_TARGET_OS": "macos",
    "CARGO_CFG_TARGET_POINTER_WIDTH": "64",
    "CARGO_CFG_TARGET_THREAD_LOCAL": "",
    "CARGO_CFG_TARGET_VENDOR": "apple",
    "CARGO_CFG_UNIX": "",
    "CARGO_MANIFEST_DIR": "/pants/src/rust/engine",
    "CARGO_PKG_AUTHORS": "Pants Build <pantsbuild@gmail.com>",
    "CARGO_PKG_DESCRIPTION": "",
    "CARGO_PKG_HOMEPAGE": "",
    "CARGO_PKG_NAME": "engine",
    "CARGO_PKG_REPOSITORY": "",
    "CARGO_PKG_VERSION": "0.0.1",
    "CARGO_PKG_VERSION_MAJOR": "0",
    "CARGO_PKG_VERSION_MINOR": "0",
    "CARGO_PKG_VERSION_PATCH": "1",
    "CARGO_PKG_VERSION_PRE": "",
    "DEBUG": "true",
    "DYLD_LIBRARY_PATH": "/pants/src/rust/engine/target/debug/deps:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib",
    "HOST": "x86_64-apple-darwin",
    "NUM_JOBS": "8",
    "OPT_LEVEL": "0",
    "OUT_DIR": "/pants/src/rust/engine/target/debug/build/engine-ba91b9939db2857c/out",
    "PROFILE": "debug",
    "RUSTC": "rustc",
    "RUSTDOC": "rustdoc",
    "TARGET": "x86_64-apple-darwin"
  },
  "cwd": "/pants/src/rust/engine"
}

result_dir = '/pants/pants.d/engine'
libraries_dir = '/pants/pants.d/deps'


class UtilsTest(unittest.TestCase):
  def get_custom_build_invocation(self):
    return copy.deepcopy(custom_build_invocation)

  def get_run_custom_build_invocation(self):
    return copy.deepcopy(run_custom_build_invocation)

  def test_args_rules_custom_invocation(self):
    args = self.get_custom_build_invocation()['args']

    AddressMock = collections.namedtuple('AddressMock', 'target_name')
    TargetMock = collections.namedtuple('TargetMock', 'address, dependencies')

    dep1_target = TargetMock(AddressMock('build_utils'), [])
    dep2_target = TargetMock(AddressMock('cbindgen'), [])
    dep3_target = TargetMock(AddressMock('cc'), [])
    target = TargetMock(AddressMock('engine'), [dep1_target, dep2_target, dep3_target])

    make_dirs = []
    crate_out_dirs = {
      'build_utils': (
        'build_utils', ['/pants/pants.d/build_utils/deps/libbuild_utils-cb8514cd7dbe5a1c.rlib']),
      'cbindgen': ('cbindgen', ['/pants/pants.d/cbindgen/deps/libcbindgen-cdeba0a445e93ac7.rlib']),
      'cc': ('cc', ['/pants/pants.d/cc/deps/libcc-6d75c99c01814b55.rlib'])
    }

    create_information = {
      'package_name': 'engine',
      'extra-filename': '-0c8d5cf2130633dc'
    }

    result = [
      "--edition=2018",
      "--crate-name",
      "build_script_cffi_build",
      "src/cffi_build.rs",
      "--color",
      "always",
      "--crate-type",
      "bin",
      "--emit=dep-info,link",
      "-C",
      "debuginfo=2",
      "-C",
      "metadata=0c8d5cf2130633dc",
      "-C",
      "extra-filename=-0c8d5cf2130633dc",
      "--out-dir",
      "/pants/pants.d/engine/build/engine-0c8d5cf2130633dc",
      "-C",
      "incremental=/pants/pants.d/engine/incremental",
      "-L",
      "dependency=/pants/pants.d/deps",
      "--extern",
      "build_utils=/pants/pants.d/build_utils/deps/libbuild_utils-cb8514cd7dbe5a1c.rlib",
      "--extern",
      "cbindgen=/pants/pants.d/cbindgen/deps/libcbindgen-cdeba0a445e93ac7.rlib",
      "--extern",
      "cc=/pants/pants.d/cc/deps/libcc-6d75c99c01814b55.rlib",
      "-C",
      "link-args=-undefined dynamic_lookup"
    ]

    args_rules(args, target, result_dir, crate_out_dirs, libraries_dir, create_information,
               make_dirs)
    print(args)
    self.assertEqual(args, result)
    self.assertEqual(make_dirs, ['/pants/pants.d/engine/build/engine-0c8d5cf2130633dc',
                                 '/pants/pants.d/engine/incremental'])

  def test_outputs_rules_custom_invocation(self):
    outputs = self.get_custom_build_invocation()['outputs']
    create_information = {
      'package_name': 'engine',
      'extra-filename': '-0c8d5cf2130633dc'
    }
    make_dirs = []
    outputs_rules(outputs, result_dir, create_information, make_dirs)

    self.assertEqual(outputs, [
      '/pants/pants.d/engine/build/engine-0c8d5cf2130633dc/build_script_cffi_build-0c8d5cf2130633dc'])
    self.assertEqual(make_dirs, ['/pants/pants.d/engine/build/engine-0c8d5cf2130633dc'])

  def test_links_rules_custom_invocation(self):
    links = self.get_custom_build_invocation()['links']
    create_information = {
      'package_name': 'engine',
      'extra-filename': '-0c8d5cf2130633dc'
    }

    links_rules(links, result_dir, create_information)

    self.assertEqual(links, {
      "/pants/pants.d/engine/build/engine-0c8d5cf2130633dc/build-script-cffi_build": "/pants/pants.d/engine/build/engine-0c8d5cf2130633dc/build_script_cffi_build-0c8d5cf2130633dc"})

  def test_program_rules_run_custom_invocation(self):
    invocation = self.get_run_custom_build_invocation()

    AddressMock = collections.namedtuple('AddressMock', 'target_name')
    TargetMock = collections.namedtuple('TargetMock', 'address, dependencies')

    dep_target = TargetMock(AddressMock('engine_custom_build'), [])
    target = TargetMock(AddressMock('engine_run_custom_build'), [dep_target])

    crate_out_dirs = {
      'engine_custom_build': (None, {
        "/pants/pants.d/engine/build/engine-ba91b9939db2857c/build-script-cffi_build": "/pants/pants.d/engine/build/engine-ba91b9939db2857c/build_script_cffi_build-0c8d5cf2130633dc"})
    }

    program_rules(target, crate_out_dirs, invocation)
    self.assertEqual(invocation['program'],
                     '/pants/pants.d/engine/build/engine-ba91b9939db2857c/build-script-cffi_build')

  def test_env_rules_run_custom_invocation(self):
    env = self.get_run_custom_build_invocation()['env']
    make_dirs = []
    env_rules(env, result_dir, libraries_dir, make_dirs)
    self.assertEqual(env['DYLD_LIBRARY_PATH'],
                     '/pants/pants.d/deps:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib')
    self.assertEqual(env['OUT_DIR'],
                     '/pants/pants.d/engine/build/engine-ba91b9939db2857c/out')
    self.assertEqual(make_dirs, ['/pants/pants.d/engine/build/engine-ba91b9939db2857c/out'])
