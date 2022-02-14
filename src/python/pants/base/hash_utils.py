# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import json
import logging
import typing
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Set
from enum import Enum
from typing import Any

from pants.util.ordered_set import OrderedSet
from pants.util.strutil import ensure_binary

logger = logging.getLogger(__name__)


def hash_all(strs: typing.Iterable[bytes | str]) -> str:
    """Returns a hash of the concatenation of all the strings in strs using sha1."""
    digest = hashlib.sha1()
    for s in strs:
        s = ensure_binary(s)
        digest.update(s)
    return digest.hexdigest()


class CoercingEncoder(json.JSONEncoder):
    """An encoder which performs coercions in order to serialize many otherwise illegal objects.

    The python documentation (https://docs.python.org/3/library/json.html#json.dumps) states that
    dict keys are coerced to strings in json.dumps, but this appears to be incorrect -- it throws a
    TypeError on things we might to throw at it, like a set, or a dict with tuple keys.
    """

    def _maybe_encode_dict_key(self, key_obj):
        # If dict keys aren't strings, recursively encode them until they are. Checking for strings here
        # means we don't touch keys that are already strings (instead of quoting them).
        if isinstance(key_obj, bytes):
            # Bytes often occur as dict keys in python 2 code, but in python 3, trying to encode bytes
            # keys raises a TypeError. We explicitly check for that here and convert to str.
            return self.default(key_obj.decode())
        elif isinstance(key_obj, str):
            return self.default(key_obj)
        else:
            return self.encode(key_obj)

    def _is_natively_encodable(self, o):
        return isinstance(o, (type(None), bool, int, list, str, bytes, float))

    def default(self, o):
        if self._is_natively_encodable(o):
            # isinstance() checks are expensive, particularly for abstract base classes such as Mapping:
            # https://stackoverflow.com/questions/42378726/why-is-checking-isinstancesomething-mapping-so-slow
            # This means that, if we let natively encodable types all through, we incur a performance hit, since
            # we call this function very often.
            # TODO(#7658) Figure out why we call this function so often.
            return o
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, Mapping):
            # Preserve order to avoid collisions for OrderedDict inputs to json.dumps(). We don't do this
            # for general mappings because dicts have an arbitrary key ordering in some versions of python
            # 3 (2.7 and 3.6-3.7 are known to have sorted keys, but with different definitions of sorted
            # orders across versions, including insertion order). We want unordered dicts to collide if
            # they have the same keys, in the same way we special-case sets below. Calling sorted() should
            # be very fast if the keys happen to be pre-sorted. Pants options don't support OrderedDict
            # inputs, and allowing them creates an ambiguity we don't need to deal with right now. See
            # discussion in #6475.
            if isinstance(o, OrderedDict):
                raise TypeError(
                    "{cls} does not support OrderedDict inputs: {val!r}.".format(
                        cls=type(self).__name__, val=o
                    )
                )
            # TODO(#7082): we can remove the sorted() and OrderedDict when we drop python 2.7 and simply
            # ensure we encode the keys/values as we do right here.
            ordered_kv_pairs = sorted(o.items(), key=lambda x: x[0])
            return OrderedDict(
                (self._maybe_encode_dict_key(k), self.default(v)) for k, v in ordered_kv_pairs
            )
        if isinstance(o, Set):
            # We disallow OrderedSet (although it is not a stdlib collection) for the same reasons as
            # OrderedDict above.
            if isinstance(o, OrderedSet):
                raise TypeError(f"{type(self).__name__} does not support OrderedSet inputs: {o!r}.")
            # Set order is arbitrary in python 3.6 and 3.7, so we need to keep this sorted() call.
            return sorted(self.default(i) for i in o)
        if isinstance(o, Iterable) and not isinstance(o, (bytes, list, str)):
            return [self.default(i) for i in o]
        logger.debug(
            f"Our custom json encoder {type(self).__name__} is trying to hash a primitive type, but has gone through"
            "checking every other registered type class before. These checks are expensive,"
            f"so you should consider registering the type {type(o)} within"
            f"this function ({type(self).__name__}.default)"
        )
        return o

    def encode(self, o):
        return super().encode(self.default(o))


def json_hash(obj: Any, encoder: type[json.JSONEncoder] | None = CoercingEncoder) -> str:
    """Hashes `obj` by dumping to JSON.

    :API: public
    """
    json_str = json.dumps(obj, ensure_ascii=True, allow_nan=False, sort_keys=True, cls=encoder)
    return hash_all([json_str])
