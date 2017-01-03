# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import subprocess

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ProtobufIntegrationTest(PantsRunIntegrationTest):

  def test_import_from_buildroot(self):
    pants_run = self.run_pants(
      ['gen.protoc', '--import-from-root',
       'testprojects/src/protobuf/org/pantsbuild/testproject/import_from_buildroot/bar'])
    self.assert_success(pants_run)

  def test_bundle_protobuf_normal(self):
    with self.pants_results(['bundle.jvm',
                              '--deployjar',
                              'examples/src/java/org/pantsbuild/example/protobuf/distance']
                            ) as pants_run:
      self.assert_success(pants_run)
      out_path = os.path.join(get_buildroot(), 'dist',
                              ('examples.src.java.org.pantsbuild.example.protobuf.distance'
                               '.distance-bundle'))
      java_run = subprocess.Popen(['java', '-cp', 'protobuf-example.jar',
                                   'org.pantsbuild.example.protobuf.distance.ExampleProtobuf'],
                                  stdout=subprocess.PIPE,
                                  cwd=out_path)
      java_retcode = java_run.wait()
      java_out = java_run.stdout.read()
      self.assertEquals(java_retcode, 0)
      self.assertIn("parsec", java_out)

  def test_bundle_protobuf_imports(self):
    with self.pants_results(['bundle.jvm',
                         '--deployjar',
                         'examples/src/java/org/pantsbuild/example/protobuf/imports']
                        ) as pants_run:
      self.assert_success(pants_run)
      out_path = os.path.join(get_buildroot(), 'dist',
                              ('examples.src.java.org.pantsbuild.example.protobuf.imports'
                               '.imports-bundle'))
      java_run = subprocess.Popen(
        ['java', '-cp', 'protobuf-imports-example.jar',
         'org.pantsbuild.example.protobuf.imports.ExampleProtobufImports'],
        stdout=subprocess.PIPE,
        cwd=out_path)
      java_retcode = java_run.wait()
      java_out = java_run.stdout.read()
      self.assertEquals(java_retcode, 0)
      self.assertIn("very test", java_out)

  def test_bundle_protobuf_unpacked_jars(self):
    with self.pants_results(['bundle.jvm',
                         '--deployjar',
                         'examples/src/java/org/pantsbuild/example/protobuf/unpacked_jars']
                        ) as pants_run:
      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal bundle run expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))
      out_path = os.path.join(get_buildroot(), 'dist',
                              ('examples.src.java.org.pantsbuild.example.protobuf.unpacked_jars'
                               '.unpacked_jars-bundle'))
      args = ['java', '-cp', 'protobuf-unpacked-jars-example.jar',
              'org.pantsbuild.example.protobuf.unpacked_jars.ExampleProtobufExternalArchive']
      java_run = subprocess.Popen(args, stdout=subprocess.PIPE, cwd=out_path)
      java_retcode = java_run.wait()
      java_out = java_run.stdout.read()
      self.assertEquals(java_retcode, 0)
      self.assertIn("Message is: Hello World!", java_out)

  def test_source_ordering(self):
    # force a compile to happen, we count on compile output in this test
    self.assert_success(self.run_pants(['clean-all']))

    # TODO(John Sirois): We should not have to pass `--no-colors` since the pants subprocess
    # has no terminal attached - ie: colors should be turned off by default in this case.
    pants_run = self.run_pants(['gen.protoc',
                                'testprojects/src/java/org/pantsbuild/testproject/proto-ordering',
                                '--level=debug',
                                '--no-colors'])
    self.assert_success(pants_run)

    def pairs(iterable):
      return [(iterable[i], iterable[i + 1]) for i in range(len(iterable) - 1)]

    def find_protoc_blocks(lines):
      split_pattern = re.compile(r'Executing: .*?\bprotoc')
      split_points = [index for index, line in enumerate(lines)
                      if split_pattern.search(line) or not line]
      return [lines[start:end] for start, end in pairs(split_points + [-1, ]) if lines[start]]

    # Scraping debug statements for protoc compilation.
    all_blocks = list(find_protoc_blocks([l.strip() for l in pants_run.stdout_data.split('\n')]))
    block_text = '\n\n'.join('[block {0}]\n{1}'.format(index, '\n'.join(block))
                              for index, block in enumerate(all_blocks))
    self.assertEquals(len(all_blocks), 3,
        'Expected there to be exactly {expected} protoc compilation group! (Were {count}.)'
        '\n{out}\n\nBLOCKS:\n{blocks}'
        .format(expected=3, count=len(all_blocks),
                out=pants_run.stderr_data,
                blocks=block_text))

    biggest_proto = -1
    for block in all_blocks:
      last_proto = -1
      seen_extracted = False
      for line in block:
        # Make sure import bases appear after the bases for actual sources.
        if line.startswith('--proto_path='):
          if re.search(r'\bextracted\b', line):
            seen_extracted = True
          else:
            self.assertFalse(seen_extracted,
                             'Local protoc bases must be ordered before imported bases!')
          continue
        # Check to make sure, eg, testproto4.proto never precedes testproto2.proto.
        match = re.search(r'(?P<sequence>\d+)\.proto[\\.]?$', line)
        if match:
          number = int(match.group('sequence'))
          self.assertTrue(number > last_proto, '{proto} succeeded proto #{number}!\n{blocks}'
                          .format(proto=line, number=last_proto, blocks=block_text))
          last_proto = number
      if last_proto > biggest_proto:
        biggest_proto = last_proto
    self.assertEquals(biggest_proto, 6, 'Not all protos were seen!\n{}'.format(block_text))
