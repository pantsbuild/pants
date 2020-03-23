# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import json
import logging
import typing
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Set
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Type, Union

from typing_extensions import Protocol

from pants.util.ordered_set import OrderedSet
from pants.util.strutil import ensure_binary

logger = logging.getLogger(__name__)


class Digest(Protocol):
    """A post-hoc type stub for hashlib digest objects."""

    def update(self, data: bytes) -> None:
        ...

    def hexdigest(self) -> str:
        ...


def hash_all(strs: typing.Iterable[Union[bytes, str]], digest: Optional[Digest] = None) -> str:
    """Returns a hash of the concatenation of all the strings in strs.

    If a hashlib message digest is not supplied a new sha1 message digest is used.
    """
    digest = digest or hashlib.sha1()
    for s in strs:
        s = ensure_binary(s)
        digest.update(s)
    return digest.hexdigest()


def hash_file(path: Union[str, Path], digest: Optional[Digest] = None) -> str:
    """Hashes the contents of the file at the given path and returns the hash digest in hex form.

    If a hashlib message digest is not supplied a new sha1 message digest is used.
    """
    digest = digest or hashlib.sha1()
    with open(path, "rb") as fd:
        s = fd.read(8192)
        while s:
            digest.update(s)
            s = fd.read(8192)
    return digest.hexdigest()


def hash_dir(path: Path, *, digest: Optional[Digest] = None) -> str:
    """Hashes the recursive contents under the given directory path.

    If a hashlib message digest is not supplied a new sha1 message digest is used.
    """
    if not isinstance(path, Path):
        raise TypeError(f"Expected path to be a pathlib.Path, given a: {type(path)}")

    if not path.is_dir():
        raise ValueError(f"Expected path to de a directory, given: {path}")

    digest = digest or hashlib.sha1()
    root = path.resolve()
    for pth in sorted(p for p in root.rglob("*")):
        digest.update(bytes(pth.relative_to(root)))
        if not pth.is_dir():
            hash_file(pth, digest=digest)
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
                raise TypeError(
                    "{cls} does not support OrderedSet inputs: {val!r}.".format(
                        cls=type(self).__name__, val=o
                    )
                )
            # Set order is arbitrary in python 3.6 and 3.7, so we need to keep this sorted() call.
            return sorted(self.default(i) for i in o)
        if isinstance(o, Iterable) and not isinstance(o, (bytes, list, str)):
            return list(self.default(i) for i in o)
        logger.debug(
            "Our custom json encoder {} is trying to hash a primitive type, but has gone through"
            "checking every other registered type class before. These checks are expensive,"
            "so you should consider registering the type {} within"
            "this function ({}.default)".format(type(self).__name__, type(o), type(self).__name__)
        )
        return o

    def encode(self, o):
        return super().encode(self.default(o))


def json_hash(
    obj: Any, digest: Optional[Digest] = None, encoder: Optional[Type[json.JSONEncoder]] = None
) -> str:
    """Hashes `obj` by dumping to JSON.

    :param obj: An object that can be rendered to json using the given `encoder`.
    :param digest: An optional `hashlib` compatible message digest. Defaults to `hashlib.sha1`.
    :param encoder: An optional custom json encoder.
    :type encoder: :class:`json.JSONEncoder`
    :returns: A hash of the given `obj` according to the given `encoder`.
    :rtype: str

    :API: public
    """
    json_str = json.dumps(obj, ensure_ascii=True, allow_nan=False, sort_keys=True, cls=encoder)
    return hash_all([json_str], digest=digest)


# TODO(#6513): something like python 3's @lru_cache decorator could be useful here!
def stable_json_sha1(obj: Any, digest: Optional[Digest] = None) -> str:
    """Hashes `obj` stably; ie repeated calls with the same inputs will produce the same hash.

    :param obj: An object that can be rendered to json using a :class:`CoercingEncoder`.
    :param digest: An optional `hashlib` compatible message digest. Defaults to `hashlib.sha1`.
    :returns: A stable hash of the given `obj`.
    :rtype: str

    :API: public
    """
    return json_hash(obj, digest=digest, encoder=CoercingEncoder)


class Sharder:
    """Assigns strings to shards pseudo-randomly, but stably."""

    class InvalidShardSpec(Exception):
        """Indicates an invalid shard spec."""

        def __init__(self, shard_spec):
            """
            :param string shard_spec: A string of the form M/N where M, N are ints and 0 <= M < N.
            """
            super(Sharder.InvalidShardSpec, self).__init__(
                "Invalid shard spec '{}', should be of the form M/N, where M, N are ints "
                "and 0 <= M < N.".format(shard_spec)
            )

    @staticmethod
    def compute_shard(s, mod):
        """Computes the mod-hash of the given string, using a sha1 hash.

        :param string s: The string to compute a shard for.
        """
        return int(hash_all([s]), 16) % mod

    def __init__(self, shard_spec):
        """
        :param string shard_spec: A string of the form M/N where M, N are ints and 0 <= M < N.
        """

        def ensure_int(s):
            try:
                return int(s)
            except ValueError:
                raise self.InvalidShardSpec(shard_spec)

        if shard_spec is None:
            raise self.InvalidShardSpec("None")
        shard_str, _, nshards_str = shard_spec.partition("/")
        self._shard = ensure_int(shard_str)
        self._nshards = ensure_int(nshards_str)

        if self._shard < 0 or self._shard >= self._nshards:
            raise self.InvalidShardSpec(shard_spec)

    def is_in_shard(self, s):
        """Returns True iff the string s is in this shard.

        :param string s: The string to check.
        """
        return self.compute_shard(s, self._nshards) == self._shard

    @property
    def shard(self):
        return self._shard

    @property
    def nshards(self):
        return self._nshards
