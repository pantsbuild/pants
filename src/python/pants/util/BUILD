# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='tests',
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/testutil:test_base',
    ':argutil',
    ':collections',
    ':contextutil',
    ':dirutil',
    ':enums',
    ':eval',
    ':fileutil',
    ':filtering',
    ':frozendict',
    ':memo',
    ':meta',
    ':netrc',
    ':objects',
    ':ordered_set',
    ':osutil',
    ':process_handler',
    ':retry',
    ':rwbuf',
    ':socket',
    ':strutil',
    ':tarutil',
    ':xml_parser',
  ],
  tags = {},
)

python_library(
  name = 'argutil',
  sources = ['argutil.py'],
  tags = {},
)

python_library(
  name = 'contextutil',
  sources = ['contextutil.py'],
  dependencies = [
    '3rdparty/python:ansicolors',
    ':dirutil',
    ':tarutil',
  ],
  tags = {},
)

python_library(
  name = 'collections',
  sources = ['collections.py'],
  tags = {},
)

python_library(
  name = 'desktop',
  sources = ['desktop.py'],
  dependencies = [
    ':osutil',
  ],
  tags = {},
)

python_library(
  name = 'dirutil',
  sources = ['dirutil.py'],
  dependencies = [
    ':strutil',
    '3rdparty/python:typing-extensions',
  ],
  tags = {},
)

python_library(
  name = 'enums',
  sources = ['enums.py'],
  tags = {},
)

python_library(
  name = 'eval',
  sources = ['eval.py'],
  tags = {},
)

python_library(
  name = 'fileutil',
  sources = ['fileutil.py'],
  dependencies = [
    ':contextutil',
  ],
  tags = {},
)

python_library(
  name = 'filtering',
  sources = ['filtering.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
  ],
  tags = {},
)

python_library(
  name = 'frozendict',
  sources = ['frozendict.py'],
  tags = {},
)

python_library(
  name = 'logging',
  sources = ['logging.py'],
  tags = {},
)

python_library(
  name = 'memo',
  sources = ['memo.py'],
  dependencies = [
    ':meta'
  ],
  tags = {},
)

python_library(
  name = 'meta',
  sources = ['meta.py'],
  dependencies = [
    '3rdparty/python:dataclasses'
  ],
  tags = {},
)

python_library(
  name = 'netrc',
  sources = ['netrc.py'],
  tags = {},
)

python_library(
  name = 'objects',
  sources = ['objects.py'],
  tags = {},
)

python_library(
  name = 'ordered_set',
  sources = ['ordered_set.py'],
  tags = {},
)

python_library(
  name = 'osutil',
  sources = ['osutil.py'],
  tags = {},
)

python_library(
  name = 'process_handler',
  sources = ['process_handler.py'],
  tags = {},
)

python_library(
  name = 'retry',
  sources = ['retry.py'],
  tags = {},
)

python_library(
  name = 'rwbuf',
  sources = ['rwbuf.py'],
  tags = {},
)

python_binary(
  name = 's3_log_aggregator',
  sources = ['s3_log_aggregator.py'],
  entry_point = 'pants.util.s3_log_aggregator',
  dependencies = [
    '3rdparty/python:s3logparse'
  ],
  tags = {},
)

python_library(
  name = 'socket',
  sources = ['socket.py'],
  tags = {},
)

python_library(
  name = 'strutil',
  sources = ['strutil.py'],
  tags = {},
)

python_library(
  name = 'tarutil',
  sources = ['tarutil.py'],
  tags = {},
)

python_library(
  name = 'xml_parser',
  sources = ['xml_parser.py'],
  tags = {},
)
