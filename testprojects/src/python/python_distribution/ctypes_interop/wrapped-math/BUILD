ctypes_compatible_c_library(
  dependencies=[
    'testprojects/src/python/python_distribution/ctypes_interop/some-more-math',
  ],
  ctypes_native_library=native_artifact(lib_name='wrapped-math'),
  # In testing, we will invoke this target with --c-compile-strict-deps switched both on and off (to
  # test that it fails if strict_deps is on). So this target also implicitly depends on :c_math_lib.
  # strict_deps=True,
)
