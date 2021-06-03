# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# See requirements.txt in this directory to change deps.
python_requirements(
  module_mapping={
    "ansicolors": ["colors"],
    "PyYAML": ["yaml"],
    "setuptools": ["pkg_resources"],
  }
)

# Useful when using IntelliJ/PyCharm remote debugging. Importing `pydevd_pycharm` at
# the breakpoint will cause dep inference to add this dep on the remote debugger client.
python_requirement_library(
  name = "pydevd-pycharm",
  requirements=["pydevd-pycharm==203.5419.8"],
)
