# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ctypes
import logging
import os

logger = logging.getLogger(__name__)


def get_generated_shared_lib(lib_name):
    # These are the same filenames as in setup.py.
    filename = "lib{}.so".format(lib_name)
    # The data files are in the root directory, but we are in ctypes_python_pkg/.
    rel_path = os.path.join(os.path.dirname(__file__), "..", filename)
    return os.path.normpath(rel_path)


cpp_math_lib_path = get_generated_shared_lib("some-more-math")
c_wrapped_math_lib_path = get_generated_shared_lib("wrapped-math")

cpp_math_lib = ctypes.CDLL(cpp_math_lib_path)
c_wrapped_math_lib = ctypes.CDLL(c_wrapped_math_lib_path)


def f(x):
    some_cpp_math_result = cpp_math_lib.add_two(x) + cpp_math_lib.multiply_by_three(x)
    logger.debug("some_cpp_math_result: {}".format(some_cpp_math_result))
    some_c_wrapped_math_result = (
        c_wrapped_math_lib.add_two(x)
        + c_wrapped_math_lib.multiply_by_three(x)
        + c_wrapped_math_lib.wrapped_function(x)
    )
    logger.debug("some_c_wrapped_math_result: {}".format(some_c_wrapped_math_result))
    return some_cpp_math_result * some_c_wrapped_math_result
