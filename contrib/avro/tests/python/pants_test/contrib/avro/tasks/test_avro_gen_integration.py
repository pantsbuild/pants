# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class AvroJavaGenTest(PantsRunIntegrationTest):
  @classmethod
  def hermetic(cls):
    return True

  def run_pants_with_workdir(self, command, workdir, config=None, stdin_data=None, extra_env=None,
                             build_root=None, tee_output=False, **kwargs):
    full_config = {
      'GLOBAL': {
        'pythonpath': ["%(buildroot)s/contrib/avro/src/python"],
        'backend_packages': ["pants.backend.codegen", "pants.backend.jvm", "pants.contrib.avro"],
      }
    }
    if config:
      for scope, scoped_cfgs in config.items():
        updated = full_config.get(scope, {})
        updated.update(scoped_cfgs)
        full_config[scope] = updated
    return super(AvroJavaGenTest, self).run_pants_with_workdir(
      command=command,
      workdir=workdir,
      config=full_config,
      stdin_data= stdin_data,
      extra_env=extra_env,
      build_root=build_root,
      tee_output=build_root,
      **kwargs
    )

  @staticmethod
  def avro_test_target(target_name):
    return 'contrib/avro/tests/avro/org/pantsbuild/contrib/avro:{}'.format(target_name)

  @staticmethod
  def get_gen_root(workdir, target_spec):
    spec_as_dir_name = target_spec.replace('/', '.').replace(':', '.')
    return os.path.join(workdir, 'gen', 'avro-java', 'current', spec_as_dir_name, 'current')

  def test_schema_gen(self):
    target_spec = self.avro_test_target('user')
    with self.pants_results(['gen', target_spec]) as pants_run:
      self.assert_success(pants_run)

      output_root = self.get_gen_root(pants_run.workdir, target_spec)
      actual_files = set(os.listdir(os.path.join(output_root, 'org', 'pantsbuild', 'contrib', 'avro')))
      self.assertEquals(set(['User.java']), actual_files)

  def test_idl_gen(self):
    target_spec = self.avro_test_target('simple')
    with self.pants_results(['gen', target_spec]) as pants_run:
      self.assert_success(pants_run)

      output_root = self.get_gen_root(pants_run.workdir, target_spec)
      expected_files = set(['Kind.java', 'MD5.java', 'Simple.java', 'TestError.java', 'TestRecord.java'])
      actual_files = set(os.listdir(os.path.join(output_root, 'org', 'pantsbuild', 'contrib', 'avro')))
      self.assertEquals(expected_files, actual_files)
