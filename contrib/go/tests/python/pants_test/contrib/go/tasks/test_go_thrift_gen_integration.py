# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.file_test_util import exact_files


class GoThriftGenIntegrationTest(PantsRunIntegrationTest):

  @contextmanager
  def _create_thrift_project(self):
    with self.temporary_sourcedir() as srcdir:
      with safe_open(os.path.join(srcdir, 'src/thrift/thrifttest/duck.thrift'), 'w') as fp:
        fp.write(dedent("""
            namespace go thrifttest.duck

            struct Duck {
              1: optional string quack,
            }
            """).strip())
      with safe_open(os.path.join(srcdir, 'src/thrift/thrifttest/BUILD'), 'w') as fp:
        fp.write(dedent("""
            go_thrift_library(
              name='fleem',
              sources=['duck.thrift']
            )
            """).strip())

      with safe_open(os.path.join(srcdir, 'src/go/usethrift/example.go'), 'w') as fp:
        fp.write(dedent("""
            package usethrift

            import "thrifttest/duck"

            func whatevs() string {
              d := duck.NewDuck()
              return d.GetQuack()
            }
            """).strip())
      with safe_open(os.path.join(srcdir, 'src/go/usethrift/BUILD'), 'w') as fp:
        fp.write(dedent("""
            go_library(
              dependencies=[
                '{srcdir}/src/thrift/thrifttest:fleem'
              ]
            )
            """.format(srcdir=os.path.relpath(srcdir, get_buildroot()))).strip())

      with safe_open(os.path.join(srcdir, '3rdparty/go/github.com/apache/thrift/BUILD'), 'w') as fp:
        fp.write("go_remote_library(rev='0.9.3', pkg='lib/go/thrift')")

      config = {
        'gen.go-thrift': {
          'thrift_import_target':
              os.path.join(os.path.relpath(srcdir, get_buildroot()),
                           '3rdparty/go/github.com/apache/thrift:lib/go/thrift'),
          'thrift_import': 'github.com/apache/thrift/lib/go/thrift'
        }
      }
      yield srcdir, config

  def test_go_thrift_gen_simple(self):
    with self.temporary_workdir() as workdir:
      with self._create_thrift_project() as (srcdir, config):
        args = ['gen', os.path.join(srcdir, 'src/thrift/thrifttest:fleem')]
        pants_run = self.run_pants_with_workdir(args, workdir, config=config)
        self.assert_success(pants_run)

        # Fetch the hash for task impl version.
        go_thrift_contents = os.listdir(os.path.join(workdir, 'gen', 'go-thrift'))
        self.assertEqual(len(go_thrift_contents), 1)
        hash_dir = go_thrift_contents[0]

        target_dir = os.path.relpath(os.path.join(srcdir, 'src/thrift/thrifttest/fleem'),
                                     get_buildroot())
        root = os.path.join(workdir, 'gen', 'go-thrift', hash_dir,
                            target_dir.replace(os.path.sep, '.'), 'current')

        self.assertEquals(sorted(['src/go/thrifttest/duck/constants.go',
                                  'src/go/thrifttest/duck/ttypes.go']),
                          sorted(exact_files(root)))

  def test_go_thrift_gen_and_compile(self):
    with self.temporary_workdir() as workdir:
      with self._create_thrift_project() as (srcdir, config):
        args = ['compile.gofmt', '--skip', os.path.join(srcdir, 'src/go/usethrift')]
        pants_run = self.run_pants_with_workdir(args, workdir, config=config)

        self.assert_success(pants_run)
