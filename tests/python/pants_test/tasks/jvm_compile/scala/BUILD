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
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/backend/jvm/tasks/jvm_compile:scala'),
  ]
)
