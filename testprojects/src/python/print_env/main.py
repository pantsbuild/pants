# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys


if __name__ == "__main__":
    # Print the content of the env var given on the command line.
    print(os.environ[sys.argv[1]])
