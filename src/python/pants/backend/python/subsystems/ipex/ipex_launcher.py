# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Entrypoint script for a "dehydrated" .ipex file generated with --generate-ipex.

This script will "hydrate" a normal .pex file in the same directory, then execute it.
"""

import json
import os
import sys
import tempfile

from pex import resolver
from pex.common import open_zip
from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

APP_CODE_PREFIX = "user_files/"


def _strip_app_code_prefix(path):
    if not path.startswith(APP_CODE_PREFIX):
        raise ValueError(
            "Path {path} in IPEX-INFO did not begin with '{APP_CODE_PREFIX}'.".format(
                path=path, APP_CODE_PREFIX=APP_CODE_PREFIX
            )
        )
    return path[len(APP_CODE_PREFIX) :]


def _log(message):
    sys.stderr.write(message + "\n")


def modify_pex_info(pex_info, **kwargs):
    new_info = json.loads(pex_info.dump())
    new_info.update(kwargs)
    return PexInfo.from_json(json.dumps(new_info))


def _hydrate_pex_file(self, hydrated_pex_file):
    # We extract source files into a temporary directory before creating the pex.
    td = tempfile.mkdtemp()

    with open_zip(self) as zf:
        # Populate the pex with the pinned requirements and distribution names & hashes.
        bootstrap_info = PexInfo.from_json(zf.read("BOOTSTRAP-PEX-INFO"))
        bootstrap_builder = PEXBuilder(pex_info=bootstrap_info, interpreter=PythonInterpreter.get())

        # Populate the pex with the needed code.
        try:
            ipex_info = json.loads(zf.read("IPEX-INFO").decode("utf-8"))
            for path in ipex_info["code"]:
                unzipped_source = zf.extract(path, td)
                bootstrap_builder.add_source(
                    unzipped_source, env_filename=_strip_app_code_prefix(path)
                )
        except Exception as e:
            raise ValueError(
                "Error: {e}. The IPEX-INFO for this .ipex file was:\n{info}".format(
                    e=e, info=json.dumps(ipex_info, indent=4)
                )
            )

    # Perform a fully pinned intransitive resolve to hydrate the install cache.
    resolver_settings = ipex_info["resolver_settings"]

    resolved_distributions = resolver.resolve(
        requirements=bootstrap_info.requirements,
        cache=bootstrap_info.pex_root,
        platform="current",
        transitive=False,
        interpreter=bootstrap_builder.interpreter,
        **resolver_settings
    )
    # TODO: this shouldn't be necessary, as we should be able to use the same 'distributions' from
    # BOOTSTRAP-PEX-INFO. When the .ipex is executed, the normal pex bootstrap fails to see these
    # requirements or recognize that they should be pulled from the cache for some reason.
    for resolved_dist in resolved_distributions:
        bootstrap_builder.add_distribution(resolved_dist.distribution)

    bootstrap_builder.build(hydrated_pex_file, bytecode_compile=False)


def main(self):
    filename_base, ext = os.path.splitext(self)

    # If the ipex (this pex) is already named '.pex', ensure the output filename doesn't collide by
    # inserting an intermediate '.ipex'!
    if ext == ".pex":
        hydrated_pex_file = "{filename_base}.ipex.pex".format(filename_base=filename_base)
    else:
        hydrated_pex_file = "{filename_base}.pex".format(filename_base=filename_base)

    if not os.path.exists(hydrated_pex_file):
        _log("Hydrating {} to {}...".format(self, hydrated_pex_file))
        _hydrate_pex_file(self, hydrated_pex_file)

    os.execv(sys.executable, [sys.executable, hydrated_pex_file] + sys.argv[1:])


if __name__ == "__main__":
    self = sys.argv[0]
    main(self)
