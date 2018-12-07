# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonAWSLambdaIntegrationTest(PantsRunIntegrationTest):
  @classmethod
  def hermetic(cls):
    return True

  def test_awslambda_bundle(self):
    with temporary_dir() as distdir:
      config = {
        'GLOBAL': {
          'pants_distdir': distdir,
          'pythonpath': ['%(buildroot)s/contrib/awslambda/python/src/python'],
          'backend_packages': ['pants.backend.python', 'pants.contrib.awslambda.python'],
        }
      }

      command = [
        'bundle',
        'contrib/awslambda/python/src/python/pants/contrib/awslambda/python/examples:hello-lambda',
      ]
      pants_run = self.run_pants(command=command, config=config)
      self.assert_success(pants_run)

      # Now run the lambda via the wrapper handler injected by lambdex (note that this
      # is distinct from the pex's entry point - a handler must be a function with two arguments,
      # whereas the pex entry point is a module).
      awslambda = os.path.join(distdir, 'hello-lambda.pex')
      output = subprocess.check_output(env={'PEX_INTERPRETER': '1'}, args=[
        '{} -c "from lambdex_handler import handler; handler(None, None)"'.format(awslambda)
      ], shell=True)
      self.assertEquals('Hello from United States!'.encode('utf8'), output.strip())
