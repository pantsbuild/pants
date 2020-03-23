# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='scalajs_repl_integration',
  sources=['test_scalajs_repl_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/scalajs:examples_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=270,
)
