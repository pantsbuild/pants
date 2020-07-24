# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from urllib.parse import urlencode

import requests

from pants.reporting.reporting_server import PantsHandler, ReportingServer
from pants.testutil.test_base import TestBase
from pants.util.contextutil import http_server, temporary_dir
from pants.util.dirutil import safe_file_dump


class ReportingTest(TestBase):
    def test_poll(self):
        with temporary_dir() as dir:

            class TestPantsHandler(PantsHandler):
                def __init__(self, request, client_address, server):
                    super().__init__(
                        settings=ReportingServer.Settings(
                            info_dir=dir,
                            template_dir=dir,
                            assets_dir=dir,
                            root=dir,
                            allowed_clients=["ALL"],
                        ),
                        renderer=None,
                        request=request,
                        client_address=client_address,
                        server=server,
                    )

            safe_file_dump(os.path.join(dir, "file"), "hello")
            with http_server(TestPantsHandler) as port:
                response = requests.get(
                    "http://127.0.0.1:{}/poll?{}".format(
                        port, urlencode({"q": json.dumps([{"id": "0", "path": "file"}])}),
                    )
                )
            self.assertEqual(response.json(), {"0": "hello"})
