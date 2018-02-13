python_library(
  dependencies=[
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/subsystem',
    'testprojects/pants-plugins/src/python/test_pants_plugin/subsystems',
  ],
  provides=setup_py(
    name='test_pants_plugin',
    description='A test pants plugin',
    version='0.0.1',
    namespace_packages=[
      'test_pants_plugin',
      'test_pants_plugin.subsystems',
      # 'test_pants_plugin.targets',
    ],
  )
)
