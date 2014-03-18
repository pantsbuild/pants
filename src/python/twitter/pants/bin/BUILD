python_library(
  name = 'pants_exe',
  sources = ['pants_exe.py'],
  dependencies = [
    pants('3rdparty/python:psutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:rcfile'),
    pants('src/python/twitter/pants/commands:command'),

    # XXX these are necessary to parse BUILD.commons.  Should instead be
    # added as plugins to pants.ini
    pants('src/python/twitter/pants/python:python_chroot'),
    pants('src/python/twitter/pants/scm:git'),
    pants('src/python/twitter/pants/targets:java'),
    pants('src/python/twitter/pants/targets:jvm'),
    pants('src/python/twitter/pants/targets:scala'),
    pants('src/python/twitter/pants/tasks:args_resource_mapper'),
    pants('src/python/twitter/pants/tasks:checkstyle'),
    pants('src/python/twitter/pants/tasks:what_changed'),

    # XXX The remaining are clear abstraction leaks.
    # The goal target should be goal:run_tracker but it is inseparable from goal; also
    # an abstraction leak.
    pants('src/python/twitter/pants/goal:initialize_reporting'),
    pants('src/python/twitter/pants/goal'),
    pants('src/python/twitter/pants/reporting'),
    pants('src/python/twitter/pants/tasks:nailgun_task'),
  ],
)

python_binary(
  name = 'pants',
  entry_point = 'twitter.pants.bin.pants_exe:main',
  platforms=[
    'current',
    'linux-x86_64',
    'macosx-10.4-x86_64',
  ],
  dependencies = [
    pants(':pants_exe'),
    pants('src/python/twitter/pants/commands:pants_old'),
    pants('src/python/twitter/pants/commands:pants_new'),
  ],
)

python_binary(
  name = 'pants_new',
  entry_point = 'twitter.pants.bin.pants_exe:main',
  dependencies = [
    pants(':pants_exe'),
    pants('src/python/twitter/pants/commands:pants_new'),
  ],
)

python_binary(
  name = 'pants_old',
  entry_point = 'twitter.pants.bin.pants_exe:main',
  dependencies = [
    pants(':pants_exe'),
    pants('src/python/twitter/pants/commands:pants_old'),
  ],
)
