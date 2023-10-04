---
title: "1.25.x"
slug: "release-notes-1-25"
hidden: true
createdAt: "2020-05-02T16:56:06.248Z"
---
Some highlights:

- Replaces the `globs()` syntax in the `sources` field in BUILD files with a simpler list of file names and globs. See https://groups.google.com/forum/#!topic/pants-devel/3nmdSeyvwU0.
- Adds support for using file arguments.
- Adds Bandit security linter for Python.
- Configures Python 3.6+ as the default Python version.
- Adds `./pants test --debug` to run tests interactively.

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/1.25.x.rst) for a detailed change log.