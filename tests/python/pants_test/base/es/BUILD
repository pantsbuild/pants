python_tests(
  name = 'dumps_logs_on_signal',
  sources = ['test_dumps_logs_on_signal.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 20,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'dumps_traceback_on_sigabrt',
  sources = ['test_dumps_traceback_on_sigabrt.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 10,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'fails_ctrl_c_cffi_extern',
  sources = ['test_fails_ctrl_c_cffi_extern.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 5,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'fails_ctrl_c_on_import',
  sources = ['test_fails_ctrl_c_on_import.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 5,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'keyboardinterrupt',
  sources = ['test_keyboardinterrupt.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 10,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'logs_unhandled_exception',
  sources = ['test_logs_unhandled_exception.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 5,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'prints_traceback_on_sigusr2',
  sources = ['test_prints_traceback_on_sigusr2.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 10,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'reset_exiter',
  sources = ['test_reset_exiter.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 10,
  tags = {'platform_specific_behavior', 'integration'},
)

python_tests(
  name = 'reset_interactive_output_stream',
  sources = ['test_reset_interactive_output_stream.py'],
  dependencies = [
    'src/python/pants/base:exception_sink',
    'src/python/pants/util:osutil',
    'tests/python/pants_test:int-test',
    'testprojects/src/python:coordinated_runs_directory',
    'testprojects:pants_plugins_directory',
  ],
  timeout = 10,
  tags = {'platform_specific_behavior', 'integration'},
)
