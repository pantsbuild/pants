# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.contrib.cpp.targets.cpp_target import CppTarget


class CppLibrary(CppTarget):
  """A statically linked C++ library."""
