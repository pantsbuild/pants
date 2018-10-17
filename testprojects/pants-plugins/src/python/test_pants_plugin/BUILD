python_library(
  dependencies=[
    'testprojects/pants-plugins/3rdparty/python/pants',
    'testprojects/pants-plugins/src/python/test_pants_plugin/subsystems',
    'testprojects/pants-plugins/src/python/test_pants_plugin/tasks',
  ],
  provides=setup_py(
    name='test_pants_plugin',
    description='A test pants plugin',
    version='0.0.1',
    namespace_packages=[
      'test_pants_plugin',
      'test_pants_plugin.subsystems',
      'test_pants_plugin.tasks',
    ],
  )
)
