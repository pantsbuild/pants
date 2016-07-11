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
     '3rdparty/python:six',
     ':dirutil',
   ],
)

python_library(
  name = 'dirutil',
  sources = ['dirutil.py'],
  dependencies = [
    ':strutil',
  ],
)

python_library(
  name = 'eval',
  sources = ['eval.py'],
  dependencies = [
    '3rdparty/python:six',
  ]
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
  dependencies = [],
)

python_library(
  name = 'memo',
  sources = ['memo.py'],
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
)

python_library(
  name = 'osutil',
  sources = ['osutil.py'],
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
  dependencies = [
    '3rdparty/python:six',
  ]
)

python_library(
  name = 'socket',
  sources = ['socket.py']
)

python_library(
  name = 'strutil',
  sources = ['strutil.py'],
  dependencies = [
    '3rdparty/python:six',
  ],
)

python_library(
  name = 'timeout',
  sources = ['timeout.py'],
)

python_library(
  name = 'xml_parser',
  sources = ['xml_parser.py'],
)
