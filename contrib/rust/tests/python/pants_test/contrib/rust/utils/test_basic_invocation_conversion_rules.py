# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import copy
import unittest

from pants.contrib.rust.utils.basic_invocation_conversion_rules import (args_rules, env_rules,
                                                                        links_rules, outputs_rules)


test_invocation = {
  "package_name": "tar_api",
  "package_version": "0.0.1",
  "target_kind": [
    "lib"
  ],
  "kind": "Host",
  "compile_mode": "build",
  "outputs": [
    "/pants/src/rust/engine/target/debug/deps/libtar_api-53a91134f88352d3.rlib"
  ],
  "links": {
    "/pants/src/rust/engine/target/debug/libtar_api.rlib": "/pants/src/rust/engine/target/debug/deps/libtar_api-53a91134f88352d3.rlib"
  },
  "program": "rustc",
  "args": [
    "--edition=2018",
    "--crate-name",
    "tar_api",
    "tar_api/src/tar_api.rs",
    "--color",
    "always",
    "--crate-type",
    "lib",
    "--emit=dep-info,link",
    "-C",
    "debuginfo=2",
    "-C",
    "metadata=53a91134f88352d3",
    "-C",
    "extra-filename=-53a91134f88352d3",
    "--out-dir",
    "/pants/src/rust/engine/target/debug/deps",
    "-C",
    "incremental=/pants/src/rust/engine/target/debug/incremental",
    "-L",
    "dependency=/pants/src/rust/engine/target/debug/deps",
    "--extern",
    "flate2=/pants/src/rust/engine/target/debug/deps/libflate2-c1056eac36b91d52.rlib",
    "--extern",
    "tar=/pants/src/rust/engine/target/debug/deps/libtar-1f0a911316416d2d.rlib",
    "-C",
    "link-args=-undefined dynamic_lookup"
  ],
  "env": {
    "CARGO": "/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/bin/cargo",
    "CARGO_MANIFEST_DIR": "/pants/src/rust/engine/tar_api",
    "CARGO_PKG_AUTHORS": "Pants Build <pantsbuild@gmail.com>",
    "CARGO_PKG_DESCRIPTION": "",
    "CARGO_PKG_HOMEPAGE": "",
    "CARGO_PKG_NAME": "tar_api",
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

result_dir = '/pants/pants.d/libtar_api'
libraries_dir = '/pants/pants.d/deps'


class UtilsTest(unittest.TestCase):
  def get_invocation(self):
    return copy.deepcopy(test_invocation)

  def test_link_rules(self):
    links = self.get_invocation()['links']
    links_rules(links, result_dir)
    self.assertEqual(links, {
      '/pants/pants.d/libtar_api/libtar_api.rlib': '/pants/pants.d/libtar_api/deps/libtar_api-53a91134f88352d3.rlib'})

  def test_outputs_rules(self):
    outputs = self.get_invocation()['outputs']
    make_dirs = set()
    make_sym_links = set()
    outputs_rules(outputs, result_dir, make_dirs, make_sym_links)
    self.assertEqual(outputs, ['/pants/pants.d/libtar_api/deps/libtar_api-53a91134f88352d3.rlib'])
    self.assertEqual(make_dirs, {'/pants/pants.d/libtar_api/deps'})
    self.assertEqual(make_sym_links,
                     {'/pants/pants.d/libtar_api/deps/libtar_api-53a91134f88352d3.rlib'})

  def test_env_rules(self):
    env = self.get_invocation()['env']
    TargetMock = collections.namedtuple('TargetMock', 'dependencies')
    target = TargetMock([])
    crate_out_dirs = dict()
    env_rules(env, target, result_dir, crate_out_dirs, libraries_dir)
    self.assertEqual(env['DYLD_LIBRARY_PATH'],
                     '/pants/pants.d/deps:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib:/root/.rustup/toolchains/nightly-2018-12-31-x86_64-apple-darwin/lib')

  def test_args_rules(self):
    args = self.get_invocation()['args']
    AddressMock = collections.namedtuple('AddressMock', 'target_name')
    TargetMock = collections.namedtuple('TargetMock', 'address, dependencies')

    dep1_target = TargetMock(AddressMock('flate2'), [])
    dep2_target = TargetMock(AddressMock('tar'), [])
    target = TargetMock(AddressMock('tar_api'), [dep1_target, dep2_target])

    make_dirs = set()
    crate_out_dirs = {
      'flate2': ('flate2', ['/pants/pants.d/libflate2/deps/libflate2-c1056eac36b91d52.rlib']),
      'tar': ('tar', ['/pants/pants.d/tar/deps/libtar-1f0a911316416d2d.rlib'])
    }

    result = [
      "--edition=2018",
      "--crate-name",
      "tar_api",
      "tar_api/src/tar_api.rs",
      "--color",
      "always",
      "--crate-type",
      "lib",
      "--emit=dep-info,link",
      "-C",
      "debuginfo=2",
      "-C",
      "metadata=53a91134f88352d3",
      "-C",
      "extra-filename=-53a91134f88352d3",
      "--out-dir",
      "/pants/pants.d/libtar_api/deps",
      "-C",
      "incremental=/pants/pants.d/libtar_api/incremental",
      "-L",
      "dependency=/pants/pants.d/deps",
      "--extern",
      "flate2=/pants/pants.d/libflate2/deps/libflate2-c1056eac36b91d52.rlib",
      "--extern",
      "tar=/pants/pants.d/tar/deps/libtar-1f0a911316416d2d.rlib",
      "-C",
      "link-args=-undefined dynamic_lookup"
    ]

    args_rules(args, target, result_dir, crate_out_dirs, libraries_dir, make_dirs)
    self.assertEqual(args, result)
    self.assertEqual(make_dirs,
                     {'/pants/pants.d/libtar_api/deps', '/pants/pants.d/libtar_api/incremental'})
