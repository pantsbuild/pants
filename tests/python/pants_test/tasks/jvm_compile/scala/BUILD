target(
  name = 'scala',
  dependencies = [
    ':test_zinc_analysis',
  ],
)

python_tests(
  name = 'test_zinc_analysis',
  sources = ['test_zinc_analysis.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:scala',
    'src/python/pants/util:contextutil',
  ]
)
