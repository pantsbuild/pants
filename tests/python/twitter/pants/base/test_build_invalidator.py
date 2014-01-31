# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import hashlib
import tempfile

from contextlib import contextmanager

from twitter.common.contextutil import temporary_dir
from twitter.pants.base.build_invalidator import BuildInvalidator, CacheKeyGenerator


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


def test_cache_key_hash():
  with test_env() as (f, keygen, cache):
    key = keygen.key_for('test', [f.name])
    assert key.hash == expected_hash(f)


def test_needs_update_missing_key():
  with test_env() as (f, keygen, cache):
    key = keygen.key_for('test', [f.name])
    assert cache.needs_update(key)


def test_needs_update_after_change():
  with test_env() as (f, keygen, cache):
    key = keygen.key_for('test', [f.name])
    assert cache.needs_update(key)
    cache.update(key)
    assert not cache.needs_update(key)
    f.truncate()
    f.write('elmo')
    f.flush()
    key = keygen.key_for('test', [f.name])
    assert cache.needs_update(key)
    cache.update(key)
    assert not cache.needs_update(key)
