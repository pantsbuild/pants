# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DeferredSourcesMapperIntegration(PantsRunIntegrationTest):

  @classmethod
  def _emit_targets(cls, workdir):
    with safe_open(os.path.join(workdir, 'BUILD'), 'w') as f:
      f.write(dedent("""
      remote_sources(name='proto-7',
        dest=java_protobuf_library,
        sources_target=':external-source',
        args=dict(
          platform='java7',
        ),
      )

      remote_sources(name='proto-8',
        dest=java_protobuf_library,
        sources_target=':external-source',
        args=dict(
          platform='java8',
        ),
        dependencies=[
          ':proto-sources',
        ],
      )

      remote_sources(name='proto-sources',
        dest=resources,
        sources_target=':external-source',
      )

      unpacked_jars(name='external-source',
        libraries=[':external-source-jars'],
        include_patterns=[
          'com/squareup/testing/**/*.proto',
        ],
      )

      jar_library(name='external-source-jars',
        jars=[
          jar(org='com.squareup.testing.protolib', name='protolib-external-test', rev='0.0.2'),
        ],
      )
      """))
    return ['{}:proto-{}'.format(os.path.relpath(workdir, get_buildroot()), num) for num in (7, 8)]

  def _configured_pants_run(self, command, workdir):
    pants_run = self.run_pants_with_workdir(
      command=command,
      workdir=workdir,
      config={
        'GLOBAL': {
          'build_ignore': [],
          'pants_ignore': []
        },
        'jvm-platform': {
          'default_platform': 'java7',
          'platforms': {
            'java7': {'source': '7', 'target': '7', 'args': []},
            'java8': {'source': '8', 'target': '8', 'args': []},
          },
        },
      },
    )
    return pants_run

  def test_deferred_sources_gen_successfully(self):
    with self.temporary_workdir() as workdir:
      pants_run = self._configured_pants_run(['gen', self._emit_targets(workdir)[0]], workdir)
      self.assert_success(pants_run)

  def test_deferred_sources_export_successfully(self):
    with self.temporary_workdir() as workdir:
      proto7, proto8 = self._emit_targets(workdir)
      pants_run = self._configured_pants_run(['export', proto7, proto8], workdir)
      self.assert_success(pants_run)
      export_data = json.loads(pants_run.stdout_data)

      synthetic_proto_libraries = []
      for target in export_data['targets'].values():
        if target['is_synthetic'] and target['pants_target_type'] == 'java_protobuf_library':
          synthetic_proto_libraries.append(target)

      self.assertEqual(2, len(synthetic_proto_libraries),
                       'Got unexpected number of synthetic proto libraries.')

      synthetic7, synthetic8 = sorted(synthetic_proto_libraries, key=lambda t: t['platform'])

      self.assertIn('proto-7', synthetic7['id'])
      self.assertIn('proto-8', synthetic8['id'])
      self.assertEqual('java7', synthetic7['platform'])
      self.assertEqual('java8', synthetic8['platform'])
