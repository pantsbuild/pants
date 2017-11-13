# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name = 'wiki_page',
  sources = ['test_wiki_page.py'],
  dependencies = [
    'contrib/confluence/src/python/pants/contrib/confluence/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)
