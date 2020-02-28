# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from unittest import skipIf

PY_2 = "2"
PY_3 = "3"

PY_27 = "2.7"
PY_36 = "3.6"
PY_37 = "3.7"


def has_python_version(version):
    """Returns `True` if the current system has the specified version of python.

    :param string version: A python version string, such as 2.7, 3.
    """
    # TODO: Tests that skip unless a python interpreter is present often need the path to that
    # interpreter, and so end up calling python_interpreter_path again. Find a way to streamline this.
    return python_interpreter_path(version) is not None


def python_interpreter_path(version):
    """Returns the interpreter path if the current system has the specified version of python.

    :param string version: A python version string, such as 2.7, 3.
    :returns: the normalized path to the interpreter binary if found; otherwise `None`
    :rtype: string
    """
    try:
        command = [f"python{version}", "-c", "import sys; print(sys.executable)"]
        py_path = subprocess.check_output(command).decode().strip()
        return os.path.realpath(py_path)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def skip_unless_all_pythons_present(*versions):
    """A decorator that only runs the decorated test method if all of the specified pythons are
    present.

    :param string *versions: Python version strings, such as 2.7, 3.
    """
    missing_versions = [v for v in versions if not has_python_version(v)]
    if len(missing_versions) == 1:
        return skipIf(True, f"Could not find python {missing_versions[0]} on system. Skipping.")
    elif len(missing_versions) > 1:
        return skipIf(
            True,
            "Skipping due to the following missing required pythons: {}".format(
                ", ".join(missing_versions)
            ),
        )
    else:
        return skipIf(False, "All required pythons present, continuing with test!")


def skip_unless_python27_present(func):
    """A test skip decorator that only runs a test method if python2.7 is present."""
    return skip_unless_all_pythons_present(PY_27)(func)


def skip_unless_python3_present(func):
    """A test skip decorator that only runs a test method if python3 is present."""
    return skip_unless_all_pythons_present(PY_3)(func)


def skip_unless_python36_present(func):
    """A test skip decorator that only runs a test method if python3.6 is present."""
    return skip_unless_all_pythons_present(PY_36)(func)


def skip_unless_python27_and_python3_present(func):
    """A test skip decorator that only runs a test method if python2.7 and python3 are present."""
    return skip_unless_all_pythons_present(PY_27, PY_3)(func)


def skip_unless_python27_and_python36_present(func):
    """A test skip decorator that only runs a test method if python2.7 and python3.6 are present."""
    return skip_unless_all_pythons_present(PY_27, PY_36)(func)


def skip_unless_python36_and_python37_present(func):
    """A test skip decorator that only runs a test method if python3.6 and python3.7 are present."""
    return skip_unless_all_pythons_present(PY_36, PY_37)(func)
