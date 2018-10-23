# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import urllib
import xml.etree.ElementTree as ET

import fire
import requests


logger = logging.getLogger(__name__)


class Releaser(object):

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
        keys.append('{}\t{}'.format(key.text, urllib.quote_plus(key.text)))

    return '\n'.join(keys)

  def fetch_prebuilt_wheels(self, binary_base_url, pants_unstable_version):
    pass

  def fetch_and_check_prebuilt_wheels(self, deploy_dir):
    pass


if __name__ == '__main__':
  fire.Fire(Releaser)
