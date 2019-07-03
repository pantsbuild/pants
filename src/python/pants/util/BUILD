# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'argutil',
  sources = ['argutil.py'],
  tags = {'type_checked'},
)

python_library(
  name = 'contextutil',
  sources = ['contextutil.py'],
  dependencies = [
    '3rdparty/python:ansicolors',
    ':dirutil',
    ':tarutil',
  ],
)

python_library(
  name = 'collections',
  sources = ['collections.py'],
)

python_library(
  name = 'debug',
  sources = ['debug.py'],
)

python_library(
  name = 'desktop',
  sources = ['desktop.py'],
  dependencies = [
    ':osutil',
  ],
  tags = {'type_checked'},
)

python_library(
  name = 'dirutil',
  sources = ['dirutil.py'],
  dependencies = [
    ':strutil',
    'src/python/pants/base:deprecated',
  ],
)

python_library(
  name = 'eval',
  sources = ['eval.py'],
)

python_library(
  name = 'fileutil',
  sources = ['fileutil.py'],
  dependencies = [
    ':contextutil',
  ],
)

python_library(
  name = 'filtering',
  sources = ['filtering.py'],
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
)

python_library(
  name = 'netrc',
  sources = ['netrc.py'],
)

python_library(
  name = 'objects',
  sources = ['objects.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':strutil',
    ':memo',
    ':meta',
  ],
)

python_library(
  name = 'osutil',
  sources = ['osutil.py'],
  tags = {'type_checked'},
)

python_library(
  name = 'process_handler',
  sources = ['process_handler.py'],
)

python_library(
  name = 'retry',
  sources = ['retry.py'],
)

python_library(
  name = 'rwbuf',
  sources = ['rwbuf.py'],
)

python_library(
  name = 's3_log_aggregator',
  sources = ['s3_log_aggregator.py'],
  dependencies = [
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
)

python_library(
  name = 'strutil',
  sources = ['strutil.py'],
  tags = {'type_checked'},
)

python_library(
  name = 'tarutil',
  sources = ['tarutil.py'],
)

python_library(
  name = 'xml_parser',
  sources = ['xml_parser.py'],
)
