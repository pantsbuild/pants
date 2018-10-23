# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib
import logging
import os
import urllib
import xml.etree.ElementTree as ET

import fire
import requests
from concurrent.futures import ThreadPoolExecutor

from pants.net.http.fetcher import Fetcher
from pants.util.dirutil import safe_mkdir


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Releaser(object):

  OUTPUT_DELIMITER = '\t'

  def list_prebuilt_wheels(self, binary_base_url, deploy_pants_wheels_path,
                           deploy_3rdparty_wheels_path):
    keys = []
    for wheel_path in [deploy_pants_wheels_path, deploy_3rdparty_wheels_path]:
      url = '{}/?prefix={}'.format(binary_base_url, wheel_path)
      # can't figure out how not to get 400 with requests, so shell off to 'curl' instead.
      resp = requests.get(url, allow_redirects=True, auth=None)
      if resp.status_code != 200:
        raise requests.exceptions.HTTPError(
          'HTTP GET {} failed. You might want to remove '
          'invalid entries in ~/.netrc (e.g. `default`)'.format(url))
      wheel_listing = resp.content

      root = ET.fromstring(wheel_listing)
      ns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
      for key in root.findall('s3:Contents/s3:Key', ns):
        # Because filenames may contain characters that have different meanings
        # in URLs (namely '+'), # print the key both as url-encoded and as a file path.
        keys.append('{}{}{}'.format(key.text, self.OUTPUT_DELIMITER, urllib.quote_plus(key.text)))

    return keys

  def fetch_prebuilt_wheels(self, binary_base_url, deploy_pants_wheels_path,
                            deploy_3rdparty_wheels_path, to_dir):
    keys = self.list_prebuilt_wheels(binary_base_url,
                                     deploy_pants_wheels_path,
                                     deploy_3rdparty_wheels_path)

    if not keys:
      raise ValueError("No wheels found.")

    # Fetching the wheels in parallel
    # It is okay to have some interleaving outputs from the fetcher,
    # because we are summarizing things in the end.
    fetcher = Fetcher(os.getcwd())
    checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
    futures = []
    with ThreadPoolExecutor(max_workers=8) as executor:
      for k in keys:
        file_path, url_path = k.split(self.OUTPUT_DELIMITER)
        dest = os.path.join(to_dir, file_path)
        safe_mkdir(os.path.dirname(dest))

        url = '{}/{}'.format(binary_base_url, url_path)
        future = executor.submit(self._download, fetcher, checksummer, url, dest)
        futures.append((future, url))

    # Summarize the fetch results.
    fail = False
    for future, url in futures:
      if future.exception() is not None:
        logger.error('Failed to download: {}'.format(url))
      else:
        logger.info('Downloaded: {}'.format(url))

    if fail:
      raise fetcher.Error()

  def _download(self, fetcher, checksummer, url, dest):
    with open(dest, 'wb') as file_path:
      try:
        logger.info('\nDownloading {}'.format(url))
        fetcher.download(url,
                         listener=fetcher.ProgressListener().wrap(checksummer),
                         path_or_fd=file_path,
                         timeout_secs=30)
        logger.debug('sha1: {}'.format(checksummer.checksum))
      except fetcher.Error as e:
        raise fetcher.Error('Failed to download: {}'.format(e))


  def fetch_and_check_prebuilt_wheels(self, deploy_dir):
    # TODO
    pass


if __name__ == '__main__':
  fire.Fire(Releaser)
