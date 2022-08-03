# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys

from kubernetes import client, config, utils


def main(args: list[str]):
    config.load_kube_config()

    kube_config = client.Configuration.get_default_copy()
    kube_client = client.api_client.ApiClient(configuration=kube_config)

    parsed_manifest = utils.create_from_yaml(kube_client, args[0])
    print(parsed_manifest)


if __name__ == "__main__":
    main(sys.argv[1:])
