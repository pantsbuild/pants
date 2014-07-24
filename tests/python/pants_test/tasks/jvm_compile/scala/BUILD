python_test_suite(
  name = 'scala',
  dependencies = [
    pants(':test_zinc_analysis'),
  ],
)

python_tests(
  name = 'test_zinc_analysis',
  sources = ['test_zinc_analysis.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm/tasks/jvm_compile:scala'),
    pants('src/python/pants/util:contextutil'),
  ]
)
