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
  sources = ['example_source.py'],
)

python_tests(
  name = 'target_with_source_dep_absolute_import',
  sources = ['test_with_source_dep_absolute_import.py'],
  dependencies = [
    ':example_lib',
  ],
)

python_tests(
  name = 'target_with_source_dep_relative_import',
  sources = ['test_with_source_dep_relative_import.py'],
  dependencies = [
    ':example_lib',
  ],
)

python_tests(
  name = 'target_with_thirdparty_dep',
  sources = ['test_with_thirdparty_dep.py'],
  dependencies = [
    '3rdparty/python:future',
  ],
)

python_library(
  name = 'transitive_dep',
  source = 'example_transitive_source.py',
  dependencies = [
    ':example_lib',
  ],
)

python_tests(
  name = 'target_with_transitive_dep',
  sources = ['test_with_transitive_dep.py'],
  dependencies = [
    ':transitive_dep',
  ],
)
