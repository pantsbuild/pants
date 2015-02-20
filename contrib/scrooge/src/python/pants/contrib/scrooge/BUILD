# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks',
    'src/python/pants/goal:task_registrar',
  ],
  provides=setup_py(
    name='pantsbuild.pants.contrib.scrooge',
    version=pants_version(),
    description='Scrooge thrift generator pants plugins.',
    long_description=(
      read_contents('src/python/pants/ABOUT.rst', relative_to_buildroot=True) +
      read_contents('src/python/pants/CHANGELOG.rst', relative_to_buildroot=True)),
    url='https://github.com/pantsbuild/pants',
    license='Apache License, Version 2.0',
    zip_safe=True,
    namespace_packages=['pants'],
    classifiers=[
      'Intended Audience :: Developers',
      'License :: OSI Approved :: Apache Software License',
      # We know for a fact these OSs work but, for example, know Windows
      # does not work yet.  Take the conservative approach and only list OSs
      # we know pants works with for now.
      'Operating System :: MacOS :: MacOS X',
      'Operating System :: POSIX :: Linux',
      'Programming Language :: Python',
      'Topic :: Software Development :: Build Tools',
    ]
  )
)
