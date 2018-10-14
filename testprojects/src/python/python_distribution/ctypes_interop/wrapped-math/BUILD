ctypes_compatible_c_library(
  dependencies=[
    'testprojects/src/python/python_distribution/ctypes_interop/some-more-math',
  ],
  ctypes_native_library=native_artifact(lib_name='wrapped-math'),
  # Turning on strict_deps brings the transitive closure of all the native dependencies into the
  # compile and link tasks. In this case, this target also implicitly depends on the "some-math" C
  # library, depended on by the "some-more-math" C++ library which we explicitly depend on above.
  strict_deps=False,
)
