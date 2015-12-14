# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
import tempfile
from contextlib import contextmanager

from pants.invalidation.build_invalidator import BuildInvalidator, CacheKeyGenerator
from pants.util.contextutil import temporary_dir


TEST_CONTENT = 'muppet'


def expected_hash(tf):
  return hashlib.sha1(os.path.basename(tf.name) + TEST_CONTENT).hexdigest()


@contextmanager
def test_env(content=TEST_CONTENT):
  with temporary_dir() as d:
    with tempfile.NamedTemporaryFile() as f:
      f.write(content)
      f.flush()
      yield f, CacheKeyGenerator(), BuildInvalidator(d)


# TODO(pl): key_for is gone and wasn't really doing us much good, but we should have some tests
# that actually exercise the BuildInvalidator with real Targets that have sources and resources

# def test_cache_key_hash():
#   with test_env() as (f, keygen, cache):
#     key = keygen.key_for('test', [f.name])
#     assert key.hash == expected_hash(f)


# def test_needs_update_missing_key():
#   with test_env() as (f, keygen, cache):
#     key = keygen.key_for('test', [f.name])
#     assert cache.needs_update(key)


# def test_needs_update_after_change():
#   with test_env() as (f, keygen, cache):
#     key = keygen.key_for('test', [f.name])
#     assert cache.needs_update(key)
#     cache.update(key)
#     assert not cache.needs_update(key)
#     f.truncate()
#     f.write('elmo')
#     f.flush()
#     key = keygen.key_for('test', [f.name])
#     assert cache.needs_update(key)
#     cache.update(key)
#     assert not cache.needs_update(key)
