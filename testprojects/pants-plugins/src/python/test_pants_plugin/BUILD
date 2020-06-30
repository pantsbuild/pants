
python_library(
  dependencies=[
    'src/python/pants/base:deprecated',
    'src/python/pants/base:exception_sink',
    'src/python/pants/engine:goal',
    'src/python/pants/engine:rules',
    'src/python/pants/option',
    'testprojects/pants-plugins/3rdparty/python/pants',
  ],
  provides=setup_py(
    name='test_pants_plugin',
    description='A test pants plugin',
    version='0.0.1',
    namespace_packages=[
      'test_pants_plugin',
    ],
  )
)
