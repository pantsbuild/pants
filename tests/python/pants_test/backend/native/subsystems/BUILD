python_tests(
  dependencies=[
    'src/python/pants/backend/native',
    'src/python/pants/backend/native/config',
    'src/python/pants/backend/native/subsystems',
    'src/python/pants/backend/native/subsystems/binaries',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:osutil',
    'src/python/pants/util:process_handler',
    'src/python/pants/util:strutil',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/engine:scheduler_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
  tags={'platform_specific_behavior'},
)

python_tests(
  name='integration',
  dependencies=[
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/native/utils',
  ]
  tags={'integration', 'platform_specific_behavior'},
)
