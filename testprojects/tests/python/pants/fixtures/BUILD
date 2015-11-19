target(
  name='fixtures',
  dependencies=[
    ':bad',
    ':good',
    ':fail',
  ]
)
python_tests(
  name='bad',
  sources=['test_bad_fixtures.py'],
)

python_tests(
  name='good',
  sources=['test_pass.py'],
)

python_tests(
  name='fail',
  sources=['test_fail.py'],
)