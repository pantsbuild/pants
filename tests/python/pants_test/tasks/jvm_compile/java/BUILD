python_test_suite(
  name = 'java',
  dependencies = [
    pants(':test_java_compile_integration'),
  ],
)

python_tests(
  name = 'test_java_compile_integration',
  sources = ['test_java_compile_integration.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm/tasks/jvm_compile:java'),
    pants('src/python/pants/util:contextutil'),
    pants('tests/python/pants_test:int-test'),
  ]
)
