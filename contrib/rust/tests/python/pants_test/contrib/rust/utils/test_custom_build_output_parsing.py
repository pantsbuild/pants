# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest

from pants.contrib.rust.utils.custom_build_output_parsing import parse_multiple_cargo_statements


build_output = [
  'cargo:rustc-link-lib=static=native_engine_ffi',
  'cargo:rustc-link-search=native=pants/.pants.d/engine/out',
  'cargo:rustc-cfg=rust_1_26',
  'cargo:rustc-cfg=memchr_runtime_sse42',
  'cargo:rustc-env=PROTOC=/protobuf/protoc',
  'cargo:rustc-env=PROTOC_INCLUDE=/protobuf/include',
  'cargo:rustc-flags=-l static=samplerate',
  'cargo:rustc-flags= -l   dylib=stdc++  ',
  'cargo:rustc-flags=-l static=pfring -L /usr/local/lib',
  'cargo:rustc-flags= -l   static=pcap  -L   /usr/local/lib  '
]

unsupported_output = [
  'cargo:warning=/lmdb-sys/lmdb/libraries/liblmdb/mdb.c:10033:33: warning: unused parameter [-Wunused-parameter]',
  'cargo:warning=mdb_env_get_maxkeysize(MDB_env *env)',
  'cargo:warning=                                ^',
  'cargo:warning=1 warning generated.'
]


class UtilsTest(unittest.TestCase):
  def get_build_output(self):
    return build_output

  def test_env_rules_run_custom_invocation(self):
    output = self.get_build_output()
    result = {
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
      ]
    }
    statements = parse_multiple_cargo_statements(output)
    self.assertEqual(statements, result)
