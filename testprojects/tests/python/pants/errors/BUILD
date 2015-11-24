target(
  name='errors',
  dependencies=[
    ':error',
    ':pass',
    ':failure',
  ]
)
python_tests(
  name='error',
  sources=['test_bad_fixtures.py'],
)

python_tests(
  name='pass',
  sources=['test_pass.py'],
)

python_tests(
  name='failure',
  sources=['test_fail.py'],
)