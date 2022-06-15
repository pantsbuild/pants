# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from types import SimpleNamespace

from yamlpath import Processor  # pants: no-infer-dep
from yamlpath.common import Parsers  # pants: no-infer-dep
from yamlpath.wrappers import ConsolePrinter  # pants: no-infer-dep


def main(args: list[str]) -> None:
    logging_args = SimpleNamespace(quiet=True, verbose=False, debug=False)
    log = ConsolePrinter(logging_args)

    yaml = Parsers.get_yaml_editor()

    cfg_file = args[0]
    (yaml_data, doc_loaded) = Parsers.get_yaml_data(yaml, log, cfg_file)
    if not doc_loaded:
        exit(1)

    print(yaml_data)

    for line in sys.stdin:
        print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
