# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name = 'markdown_to_html',
  sources = ['test_markdown_to_html.py'],
  dependencies = [
    '3rdparty/python:beautifulsoup4',
    '3rdparty/python:mock',
    'src/python/pants/backend/docgen/targets',
    'src/python/pants/backend/docgen/tasks',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/tasks:task_test_base',
  ],
  coverage = [
    'pants.backend.docgen.tasks.markdown_to_html',
  ]
)

python_tests(
  name = 'markdown_to_html_integration',
  sources = ['test_markdown_to_html_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
  coverage = [
    'pants.backend.docgen.tasks.markdown_to_html',
  ],
  tags = {'integration'},
)
