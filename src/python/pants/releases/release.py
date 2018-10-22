# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

# import argparse
# import base64
# import fnmatch
# import glob
# import hashlib
# import os
# import re
# import zipfile
# from builtins import open, str
import hashlib
import logging
import os
import requests
import subprocess

#
# from pants.util.contextutil import open_zip, temporary_dir
# from pants.util.dirutil import read_file, safe_file_dump


import fire

from pants.net.http.fetcher import Fetcher
from pants.util.contextutil import temporary_file
import sys
import urllib
import xml.etree.ElementTree as ET
logger = logging.getLogger(__name__)


class Releaser(object):

  def list_prebuilt_wheels(self, binary_base_url, deploy_pants_wheels_path, deploy_3rdparty_wheels_path):
    keys = []
    for wheel_path in [deploy_pants_wheels_path, deploy_3rdparty_wheels_path]:
      url = '{}/?prefix={}'.format(binary_base_url, wheel_path)
      # can't figure out how not to get 400 with requests, so shell off to 'curl' instead.
      resp = requests.get(url, allow_redirects=True, auth=None)
      if resp.status_code != 200:
        raise requests.exceptions.HTTPError("HTTP GET {} failed. You might want to remove invalid entries in ~/.netrc (e.g. `default`)".format(url))

      wheel_listing = resp.content
      # wheel_listing = subprocess.check_output(['curl', url])

      root = ET.fromstring(wheel_listing)
      ns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}


      for key in root.findall('s3:Contents/s3:Key', ns):
        # Because filenames may contain characters that have different meanings
        # in URLs (namely '+'), # print the key both as url-encoded and as a file path.
        keys.append('{}\t{}'.format(key.text, urllib.quote_plus(key.text)))

    return keys
      # with temporary_file() as file_path:
      #   fetcher = Fetcher(os.getcwd())
      #   checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
      #   try:
      #     logger.info('\nDownloading {}'.format(url))
      #     fetcher.download(url,
      #                      listener=fetcher.ProgressListener().wrap(checksummer),
      #                      path_or_fd=file_path,
      #                      timeout_secs=5)
      #     logger.info('sha1: {}'.format(checksummer.checksum))
      #   except fetcher.Error as e:
      #     raise fetcher.Error('Failed to download: {}'.format(e))



  def fetch_prebuilt_wheels(self, binary_base_url, pants_unstable_version):
    pass


  def fetch_and_check_prebuilt_wheels(self, deploy_dir):
    print(deploy_dir)

if __name__ == '__main__':
  fire.Fire(Releaser)

