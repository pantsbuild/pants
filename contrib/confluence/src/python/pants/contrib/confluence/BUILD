# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'confluence',
  sources = rglobs('*.py'),
  dependencies = [
    '3rdparty/python/twitter/commons:log',
  ],
  provides = setup_py(
    name = 'twitter.common.confluence',
    description = 'Confluence utilities for twitter.',
    url = 'https://github.com/pantsbuild/pants',
    license = 'Apache License, Version 2.0',
    classifiers = [
      'Intended Audience :: Developers',
      'License :: OSI Approved :: Apache Software License',
      'Operating System :: OS Independent',
      'Programming Language :: Python',
    ]
  )
)