# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
    sources=["*.yaml"],
    overrides={
        "auto-cherry-picker.yaml": {
            "dependencies": [
                "//build-support/cherry_pick/package.json:support_files",
                "//build-support/cherry_pick/package-lock.json:support_files",
                "//build-support/cherry_pick/helper.js:support_files",
                "//build-support/cherry_pick/make_pr.sh:support_files",
            ]
        }
    },
)
