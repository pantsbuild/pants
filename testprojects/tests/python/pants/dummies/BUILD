python_tests(
  name = 'passing_target',
  sources = ['test_pass.py'],
)

python_tests(
  name = 'failing_target',
  sources = ['test_fail.py'],
)

python_library(
  name = 'example_lib',
  sources = 'example_source.py',
)

python_tests(
  name = 'target_with_source_dep',
  sources = ['test_with_source_dep.py'],
  dependencies = [
    ':example_lib',
  ],
)
