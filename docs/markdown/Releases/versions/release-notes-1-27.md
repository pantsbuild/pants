---
title: "1.27.x"
slug: "release-notes-1-27"
hidden: true
createdAt: "2020-05-02T04:58:34.103Z"
---
Some highlights:

- Improved formatting of `./pants help` and `./pants goals`.
- `.gitignore` will auto-populate the global option `--pants-ignore`, by default, through the new global option `--pants-use-gitignore`.
- The `dependencies` goal has a new `--type=3rdparty` option to list the requirement strings of your third-party dependencies.
- The `filedeps` goal has a new `--transitive` flag to include all used files from dependencies, instead of only files used the target itself.
- `./pants binary` will now use all fields defined on a `python_binary` target, like `zip_safe` and `platforms`.
- When resolving third-party Python dependencies, you can now use the `repos` option in `[python-setup]` to use custom repositories other than PyPI.
- `./pants binary` and `./pants run` better support globs of targets; they will filter out all irrelevant targets for you.
- `./pants -ldebug` and `-ltrace` will enable logging in PEX for better troubleshooting.
- Pytest coverage reports can be written to the console through `--pytest-coverage-report=console`.
- Pytest coverage reports can be automatically opened through `./pants test --open-coverage`.
- Fixed how interpreter constraints are applied from dependencies.

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/1.27.x.rst) for a detailed change log.