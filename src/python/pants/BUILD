# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

dependencies(
  name = 'pants',
  dependencies = [
    pants('src/python/pants/bin:pants'),
  ],
).with_description('An alias for the pants binary target.')

python_library(
  name = 'pants-packaged',

  # TODO(wickman) This version should be automatically pulled in from pants.version
  provides=setup_py(
    name='pants',
    version='0.0.17',
    description="Twitter's pants build tool.",
    url='https://github.com/twitter/commons',
    license='Apache License, Version 2.0',
    zip_safe=True,
    namespace_packages=['twitter'],
    classifiers=[
      'Intended Audience :: Developers',
      'License :: OSI Approved :: Apache Software License',
      'Operating System :: OS Independent',
      'Programming Language :: Python',
    ]
  ).with_binaries(
    # TODO(John Sirois): Switch back when target cycles have been sorted out.
    # pants=pants('src/python/pants/bin:pants'),
    pants=pants(':_pants_transitional_publishable_binary_'),
  )
)

page(name='readme',
  source='README.md',
)

# XXX move into base or thrift
python_library(
  name = 'binary_util',
  sources = ['binary_util.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/tasks:task_error'),
  ],
)

python_library(
  name = 'thrift_util',
  sources = ['thrift_util.py'],
  dependencies = [
    pants(':binary_util'),
  ],
)
