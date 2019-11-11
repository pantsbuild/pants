python_library(
    dependencies = [
      '3rdparty/python:dataclasses',
      'src/python/pants/base:build_root',
      'src/python/pants/base:exiter',
      'src/python/pants/build_graph',
      'src/python/pants/engine:goal',
      'src/python/pants/engine:rules',
      'src/python/pants/engine:interactive_runner',
      'src/python/pants/engine:selectors',
      'src/python/pants/engine:addressable',
      'src/python/pants/engine:console',
      'src/python/pants/engine/legacy:graph',
      'src/python/pants/goal',
      'src/python/pants/source',
      'src/python/pants/util:collections',
    ]
)

python_tests(
  name = "tests",
  dependencies = [
    ':core',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil:console_rule_test_base',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil/subsystem',
  ]
)

