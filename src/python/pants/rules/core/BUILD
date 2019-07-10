python_library()

python_tests(
  name = 'roots',
  sources = ['test_list_roots.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/build_graph',
    'src/python/pants/backend/python/targets:python',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:console_rule_test_base',
  ],
)

