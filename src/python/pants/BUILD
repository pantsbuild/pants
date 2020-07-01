# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Enable `python -m pants ...` style execution ala `json.tool` or `venv`.
python_library(
  name='entry_point',
  sources=['__main__.py'],
  dependencies=[
    'src/python/pants/bin',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='pants-packaged',
  sources=[],
  dependencies=[
    ':dummy_c',
    ':entry_point',
    ':version',
  ],
  tags = {'partially_type_checked'},
  provides=pants_setup_py(
    name='pantsbuild.pants',
    description='A scalable build tool for large, complex, heterogeneous repos.',
    namespace_packages=['pants', 'pants.backend'],
    # NB: by setting `ext_modules`, we signal to setup_py and bdist_wheel that this library
    # has native code. As a consequence, bdist_wheel pins the ABI (application binary interface)
    # used when creating the wheel, which is a good thing. We should be setting this ABI to ensure
    # consumers of pantsbuild.pants are using a compatible interpreter.
    # TODO(7344): the tuple syntax for ext_modules is deprecated. Use Extension once we support it.
    ext_modules=[('native_engine', {'sources': ['src/pants/dummy.c']})],
  ).with_binaries(
    pants='src/python/pants/bin:pants',
  )
)

# NB: we use this to avoid clang/gcc complaining `error: no input files` when building
# `:pants-packaged`. We don't actually need to use any meaningful file here, though, because we
# use `with_binaries()` to link to the actual native code, so clang/gcc do not need to build any
# native code. This is just a dummy file.
resources(
  name="dummy_c",
  sources=['dummy.c'],
)

python_library(
  name='version',
  sources=['version.py'],
  dependencies = [
    '3rdparty/python:packaging',
    ':version-resource',
  ],
  tags = {"type_checked"},
)

resources(
  name='version-resource',
  sources=['VERSION'],
)

# NB: This is used for the integration test `test_reversion.py`. It includes all transitive
# dependencies to ensure that the chroot can run `src/python/pants/releases:reversion` properly.
files(
  name='reversion_file_with_dependencies',
  sources=[
    '__init__.py',
    'releases/BUILD',
    'releases/__init__.py',
    'releases/reversion.py',
    'util/BUILD',
    'util/__init__.py',
    'util/contextutil.py',
    'util/dirutil.py',
    'util/strutil.py',
    'util/tarutil.py',
  ],
)
