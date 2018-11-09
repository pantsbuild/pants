# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import PY2, PY3


"""Custom backport of collections, due to limitations with future.moves.

future.moves.collections doesn't actually work as we intended. In Python 3, abstract classes like Mapping and 
MutableSequence were moved from collections to collections.abc. When we were using future.moves.collections,
we expected to be able to import these values like Iterable.

However, the way the source code 
(https://github.com/PythonCharmers/python-future/blob/master/src/future/moves/collections.py) is written for
future.moves.collections, it doesn't grab any of the values from collections.abc, so we were getting 
AttributeError when trying to use future.moves.collections.Iterable.

So, we created this proper backport that imports then reexports both collections and collections.abc regardless
of the Python interpreter.

Note that solution is technically Py2-first; the Py3-first solution would require creating a file collections_abc_backport.
We can do this, but it seems more confusing to me to know when you can use stdlib collections vs needing our backport.

Also note that although we only need to use our backport in ~5 files, we're using it everywhere for consistency.
"""

from collections import *  # isort:skip  # noqa: F401,F403

if PY3:
  from collections.abc import *  # noqa: F401,F403

if PY2:
  from UserDict import UserDict  # noqa: F401
  from UserList import UserList  # noqa: F401
  from UserString import UserString  # noqa: F401
