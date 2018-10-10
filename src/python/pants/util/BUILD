# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'argutil',
  sources = ['argutil.py'],
)

python_library(
  name = 'contextutil',
  sources = ['contextutil.py'],
  dependencies = [
    '3rdparty/python:ansicolors',
    '3rdparty/python:future',
    ':dirutil',
    ':tarutil',
  ],
)

python_library(
  name = 'collections',
  sources = ['collections.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'debug',
  sources = ['debug.py'],
  dependencies = [
    '3rdparty/python:future',
  ],
)

python_library(
  name = 'desktop',
  sources = ['desktop.py'],
  dependencies = [
    ':osutil',
    ':process_handler',
  ],
)

python_library(
  name = 'dirutil',
  sources = ['dirutil.py'],
  dependencies = [
    ':strutil',
    '3rdparty/python:future',
  ],
)

python_library(
  name = 'eval',
  sources = ['eval.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'fileutil',
  sources = ['fileutil.py'],
  dependencies = [
    '3rdparty/python:future',
    ':contextutil',
  ],
)

python_library(
  name = 'filtering',
  sources = ['filtering.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'memo',
  sources = ['memo.py'],
  dependencies = [
      ':meta'
  ],
)

python_library(
  name = 'meta',
  sources = ['meta.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'netrc',
  sources = ['netrc.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'objects',
  sources = ['objects.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:future',
    ':memo',
    ':meta',
  ],
)

python_library(
  name = 'osutil',
  sources = ['osutil.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'process_handler',
  sources = ['process_handler.py'],
  dependencies= [
    '3rdparty/python:future',
    '3rdparty/python:subprocess32',
    ':meta',
  ]
)

python_library(
  name = 'retry',
  sources = ['retry.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'rwbuf',
  sources = ['rwbuf.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:six',
  ]
)

python_library(
  name = 's3_log_aggregator',
  sources = ['s3_log_aggregator.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:s3logparse'
  ]
)

python_binary(
  name = 's3_log_aggregator_bin',
  entry_point = 'pants.util.s3_log_aggregator',
  dependencies = [
    ':s3_log_aggregator'
  ]
)

python_library(
  name = 'socket',
  sources = ['socket.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name = 'strutil',
  sources = ['strutil.py'],
  dependencies = [
    '3rdparty/python:future',
  ],
)

python_library(
  name = 'tarutil',
  sources = ['tarutil.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:six',
  ],
)

python_library(
  name = 'xml_parser',
  sources = ['xml_parser.py'],
)
