# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import PY2, PY3


"""Custom backport of collections.abc, due to limitations with future.moves.
In Python 3, multiple classes moved from collections to collections.abc, such as Iterable and Mapping. The backport 
future.moves.collections fails to support these values, so we must use our own custom interface.

Refer to https://github.com/PythonCharmers/python-future/blob/master/src/future/moves/collections.py for the basis of this file.
"""

from collections import *  # isort:skip  # noqa: F401,F403
	
if PY3:
  from collections.abc import *  # noqa: F401,F403

if PY2:
  from UserDict import UserDict  # noqa: F401
  from UserList import UserList  # noqa: F401
  from UserString import UserString  # noqa: F401
