# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

import requests
from colors import red


def main() -> None:
    response = requests.post(
        "https://pants-remoting-beta.appspot.com/token/generate",
        json={"travis_job_id": os.getenv("TRAVIS_JOB_ID")},
    )
    if not response.ok:
        print(red("Failed to generate a token for remote build execution."), file=sys.stderr)
        response.raise_for_status()
    print(response.text, end="")


if __name__ == "__main__":
    main()
