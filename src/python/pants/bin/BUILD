# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_exe',
  sources = ['pants_exe.py'],
  dependencies = [
    pants('3rdparty/python:psutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:rcfile'),
    pants('src/python/pants/commands:command'),

    # XXX these are necessary to parse BUILD.commons.  Should instead be
    # added as plugins to pants.ini
    pants('src/python/pants/python:python_chroot'),
    pants('src/python/pants/scm:git'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/targets:scala'),
    pants('src/python/pants/tasks:args_resource_mapper'),
    pants('src/python/pants/tasks:checkstyle'),
    pants('src/python/pants/tasks:what_changed'),

    # XXX The remaining are clear abstraction leaks.
    # The goal target should be goal:run_tracker but it is inseparable from goal; also
    # an abstraction leak.
    pants('src/python/pants/goal:initialize_reporting'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/tasks:nailgun_task'),
  ],
)

python_binary(
  name = 'pants',
  entry_point = 'pants.bin.pants_exe:main',
  platforms=[
    'current',
    'linux-x86_64',
    'macosx-10.4-x86_64',
  ],
  dependencies = [
    pants(':pants_exe'),
    pants('src/python/pants/commands:pants_old'),
    pants('src/python/pants/commands:pants_new'),
  ],
)

python_binary(
  name = 'pants_new',
  entry_point = 'pants.bin.pants_exe:main',
  dependencies = [
    pants(':pants_exe'),
    pants('src/python/pants/commands:pants_new'),
  ],
)

python_binary(
  name = 'pants_old',
  entry_point = 'pants.bin.pants_exe:main',
  dependencies = [
    pants(':pants_exe'),
    pants('src/python/pants/commands:pants_old'),
  ],
)
