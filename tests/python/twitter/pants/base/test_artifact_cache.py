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
import shutil
import tempfile

from twitter.pants.base.artifact_cache import ArtifactCache
from twitter.pants.base.build_invalidator import CacheKey
from twitter.common.contextutil import temporary_dir
from contextlib import contextmanager


TEST_CONTENT = 'muppet'

@contextmanager
def test_env(content=TEST_CONTENT):
  with temporary_dir() as d:
    with tempfile.NamedTemporaryFile() as f:
      f.write(content)
      f.flush()
      yield f, ArtifactCache(d)

def test_use_cache():
  with test_env() as (f, cache):
    key = CacheKey('muppet_key', 'fake_hash', 42)
    cache.insert(key, [f.name])
    with temporary_dir() as staging:
      abs_fn = os.path.join(staging, os.path.basename(f.name))
      assert not os.path.exists(abs_fn)
      cache.use_cached_files(key, lambda s, d: shutil.copyfile(s, os.path.join(staging, d)))
      assert os.path.exists(abs_fn)
      with open(abs_fn) as fd:
        assert fd.read() == TEST_CONTENT
