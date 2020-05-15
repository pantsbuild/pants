# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'argutil',
  sources = ['test_argutil.py'],
  coverage = ['pants.util.argutil'],
  dependencies = [
    'src/python/pants/util:argutil',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'collections',
  sources = ['test_collections.py'],
  coverage = ['pants.util.collections'],
  dependencies = [
    'src/python/pants/util:collections',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'contextutil',
  sources = ['test_contextutil.py'],
  coverage = ['pants.util.contextutil'],
  dependencies = [
    'src/python/pants/util:contextutil',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'dirutil',
  sources = ['test_dirutil.py'],
  coverage = ['pants.util.dirutil'],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'enums',
  sources = ['test_enums.py'],
  coverage = ['pants.util.enums'],
  dependencies = [
    'src/python/pants/util:enums',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'eval',
  sources = ['test_eval.py'],
  dependencies = [
    'src/python/pants/util:eval',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'fileutil',
  sources = ['test_fileutil.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:fileutil',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'memo',
  sources = ['test_memo.py'],
  dependencies = [
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'meta',
  sources = ['test_meta.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/util:meta',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'netrc',
  sources = ['test_netrc.py'],
  dependencies = [
    'src/python/pants/util:netrc',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'objects',
  sources = ['test_objects.py'],
  coverage = ['pants.util.objects'],
  dependencies = [
    'src/python/pants/util:objects',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'osutil',
  sources = ['test_osutil.py'],
  dependencies = [
    'src/python/pants/util:osutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'process_handler',
  sources = ['test_process_handler.py'],
  dependencies = [
    'src/python/pants/util:process_handler',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'retry',
  sources = ['test_retry.py'],
  dependencies = [
    'src/python/pants/util:retry',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'rwbuf',
  sources = ['test_rwbuf.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:rwbuf',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'socket',
  sources = ['test_socket.py'],
  coverage = ['pants.util.socket'],
  dependencies = [
    'src/python/pants/util:socket',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'strutil',
  sources = ['test_strutil.py'],
  dependencies = [
    'src/python/pants/util:strutil',
  ],
  tags = {'type_checked'},
)

python_tests(
  name = 'tarutil',
  sources = ['test_tarutil.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
    'src/python/pants/util:tarutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='xml_test_base',
  sources = ['xml_test_base.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'xml_parser',
  sources = ['test_xml_parser.py'],
  dependencies = [
    'src/python/pants/util:xml_parser',
    'tests/python/pants_test/util:xml_test_base',
  ],
  tags = {"partially_type_checked"},
)
