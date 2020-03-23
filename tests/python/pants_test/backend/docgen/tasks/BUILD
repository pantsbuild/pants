# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name = 'markdown_to_html',
  sources = ['test_markdown_to_html.py'],
  dependencies = [
    '3rdparty/python:beautifulsoup4',
    'src/python/pants/backend/docgen/targets',
    'src/python/pants/backend/docgen/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'markdown_to_html_integration',
  sources = ['test_markdown_to_html_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/java/org/pantsbuild/testproject:page_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)
