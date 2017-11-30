# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

import requests

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ReversionTest(PantsRunIntegrationTest):

  def test_run(self):
    with temporary_dir() as dest_dir:
      # Download an input whl.
      # TODO: Not happy about downloading things. Attempted to:
      #  ./pants setup-py bdist_wheel -w $dest_dir
      # but was unable to locate the output whl in the context of a test (perhaps due to
      # mismatched cwd?)
      input_name = 'virtualenv-15.1.0-py2.py3-none-any.whl'
      url = (
          'https://files.pythonhosted.org/packages/6f/86/'
          '3dc328ee7b1a6419ebfac7896d882fba83c48e3561d22ddddf38294d3e83/{}'.format(input_name)
        )
      input_whl_file = os.path.join(dest_dir, input_name)
      with open(input_whl_file, 'wb') as f:
        shutil.copyfileobj(requests.get(url, stream=True).raw, f)

      # Rewrite it.
      command = [
          'run',
          '-q',
          'src/python/pants/releases:reversion',
          '--',
          input_whl_file,
          dest_dir,
          '9.1.9',
        ]
      self.assert_success(self.run_pants(command))

      # TODO: confirm usable.
