# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os


def _get_generated_shared_lib(lib_name):
    # These are the same filenames as in setup.py.
    filename = "lib{}.so".format(lib_name)
    # The data files are in the root directory.
    rel_path = os.path.join(os.path.dirname(__file__), "..", filename)
    return os.path.normpath(rel_path)


zero_out_op_lib_path = _get_generated_shared_lib("tensorflow-zero-out-operator")
