# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from typing import Tuple

import requests
from requests.exceptions import RequestException

from pants.subsystem.subsystem import Subsystem


class Workunits(Subsystem):
  options_scope = 'workunits'

  @classmethod
  def register_options(cls, register):
    register("--http-endpoint", type=str, help="Where to make HTTP requests to")

  def make_http_request(self, workunits: Tuple[dict,...]):
    options =  self.get_options()
    http_endpoint = options.http_endpoint
    data = { "workunits": workunits }

    if not http_endpoint:
      print("Streaming workunits are activated, but there is no specified HTTP endpoint to send them to")
      return

    try:
      requests.post(http_endpoint, data=json.dumps(data))
    except RequestException as e:
      print(f"Failed to make a request: {e}")
