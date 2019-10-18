# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class IsolatedProcessIntegrationTest(PantsRunIntegrationTest):

  def test_log_stats(self):
    with temporary_dir() as destdir:
      # Test that it will make a directory if it needs to:
      temp_file = os.path.join(destdir, "dir", "file.json")
      args = [
        f'--process-execution-stats-logfile={temp_file}',
        'cloc',
        'examples/src/scala/org/pantsbuild/example/hello/welcome',
      ]
      self.assert_success(self.run_pants(args))
      with open(temp_file, 'r') as f:
        obj = json.load(f)
        self.assertIn("flattened_input_digests", obj)
        self.assertIn("flattened_output_digests", obj)
