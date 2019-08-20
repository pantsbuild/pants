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
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.10/pex'
  digest = Digest('f4ac0f61f0c469537f04418e9347658340b0bce4ba61d302c5b805d194dda482', 1868106)
  snapshot = yield Get(Snapshot, UrlToFetch(url, digest))
  yield DownloadedPexBin(executable=snapshot.files[0], directory_digest=snapshot.directory_digest)


def rules():
  return [
    download_pex_bin,
  ]
