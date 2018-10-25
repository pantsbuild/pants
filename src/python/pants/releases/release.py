# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib
import logging
import os
import urllib
import xml.etree.ElementTree as ET
from contextlib import contextmanager

from builtins import open

import fire
import requests
from concurrent.futures import ThreadPoolExecutor

from pants.net.http.fetcher import Fetcher
from pants.releases.package_constants import RELEASE_PACKAGES
from pants.util.dirutil import safe_mkdir
from pants.util.process_handler import subprocess


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Releaser(object):

  OUTPUT_DELIMITER = '\t'
  ROOT = os.getcwd()
  VERSION_FILE = "{}/src/python/pants/VERSION".format(ROOT)

  def list_prebuilt_wheels(self, binary_base_url, deploy_pants_wheels_path,
                           deploy_3rdparty_wheels_path):
    wheel_paths = []
    for wheel_path in [deploy_pants_wheels_path, deploy_3rdparty_wheels_path]:
      url = '{}/?prefix={}'.format(binary_base_url, wheel_path)
      resp = requests.get(url, allow_redirects=True, auth=None)
      if resp.status_code != 200:
        raise requests.exceptions.HTTPError(
          'HTTP GET {} failed. You may have invalid entries in ~/.netrc (e.g. `default`)'.format(url))
      wheel_listing = resp.content

      root = ET.fromstring(wheel_listing)
      ns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
      for key in root.findall('s3:Contents/s3:Key', ns):
        # Because filenames may contain characters that have different meanings
        # in URLs (namely '+'), # print the key both as url-encoded and as a file path.
        wheel_paths.append('{}{}{}'.format(key.text, self.OUTPUT_DELIMITER, urllib.quote_plus(key.text)))

    return wheel_paths

  def fetch_prebuilt_wheels(self, binary_base_url, deploy_pants_wheels_path,
                            deploy_3rdparty_wheels_path, to_dir):
    wheel_paths = self.list_prebuilt_wheels(binary_base_url,
                                     deploy_pants_wheels_path,
                                     deploy_3rdparty_wheels_path)

    if not wheel_paths:
      raise ValueError("No wheels found.")

    # Fetching the wheels in parallel
    # It is okay to have some interleaving outputs from the fetcher,
    # because we are summarizing things in the end.
    fetcher = Fetcher(self.ROOT)
    checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
    futures = []
    with ThreadPoolExecutor(max_workers=8) as executor:
      for k in wheel_paths:
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
        fail = True
      else:
        logger.info('Downloaded: {}'.format(url))

    if fail:
      raise fetcher.Error()

  @classmethod
  @contextmanager
  def temporary_pants_version(cls, new_version):
    """
      A with-context that changes Pants version temporarily.
    """

    with open(Releaser.VERSION_FILE, 'r+') as f:
      previous_version = f.read()
      try:
        f.seek(0)
        f.write(new_version + '\n')
        f.truncate()
        f.flush()
        yield f
      finally:
        f.seek(0)
        f.write(previous_version)
        f.truncate()

  def build_pants_packages(self, version, deploy_pants_wheel_dir, release_packages):

    with self.temporary_pants_version(version):
      # Sanity check the packages to be built
      packages = release_packages.split()
      assert len(packages) == len(RELEASE_PACKAGES)
      logger.info('Going to build:\n{}'.format('\n'.join(p.name for p in RELEASE_PACKAGES)))
      for package in RELEASE_PACKAGES:
        args = [
          './pants',
          'setup-py',
          '--run=bdist_wheel {}'.format(
            package.bdist_wheel_flags if package.bdist_wheel_flags else '--python-tag py27'),
          package.build_target]
        logger.info('Building {}'.format(package.name))
        logger.info(' '.join("'{}'".format(a) for a in args))
        subprocess.check_output(args)

        built_wheel = self._find_pkg(pkg_name=package.name, version=version,
                                     search_dir=os.path.join(self.ROOT, 'dist'))

        self._cp_built_wheels_to_wheels_dir(built_wheel,
                                            os.path.join(deploy_pants_wheel_dir, version))

  @classmethod
  def _cp_built_wheels_to_wheels_dir(cls, built_wheel,final_wheel_location):
    args = ['cp', '-p', built_wheel, final_wheel_location]
    subprocess.check_output(args)

  def _find_pkg(self, pkg_name, version, search_dir):
    args = ['find', search_dir, '-type', 'f', '-name', '{}-{}-*.whl'.format(pkg_name, version)]
    output = subprocess.check_output(args)
    lines = output.splitlines()
    if len(lines) != 1:
      raise ValueError("Exactly one wheel is expected to be found, but found: {}".format(lines))
    return lines[0]

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
