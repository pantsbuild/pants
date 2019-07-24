# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.fs import Digest, Snapshot, UrlToFetch
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.util.objects import datatype


class DownloadedPexBin(datatype([('executable', str), ('directory_digest', Digest)])):
  pass


@rule(DownloadedPexBin, [])
def download_pex_bin():
  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.8/pex'
  digest = Digest('2ca320aede7e7bbcb907af54c9de832707a1df965fb5a0d560f2df29ba8a2f3d', 1866441)
  snapshot = yield Get(Snapshot, UrlToFetch(url, digest))
  yield DownloadedPexBin(executable=snapshot.files[0], directory_digest=snapshot.directory_digest)


def rules():
  return [
    download_pex_bin,
  ]
