---
title: "1.26.x"
slug: "release-notes-1-26"
hidden: true
createdAt: "2020-05-02T04:58:34.851Z"
---
Some highlights:

- Pants now uses Pex 2.1, which uses Pip instead of its own custom resolver. See https://github.com/pantsbuild/pex/pull/788 for details.
- Adds support for `pants.toml` as an improvement on the now legacy `pants.ini` format. See https://groups.google.com/forum/#!topic/pants-devel/N1H03oJONco for details.
- Adds support for Python lockfiles.
- Adds the Pylint linter.
- Adds IPython support to `./pants repl`.
- Adds support for getting coverage data with `./pants test`.
- When using file arguments with `./.pants test`, `fmt`, or `lint`, Pants now runs over only the files specified, rather than all files belonging to the owning target.
- Changes `./pants fmt` and `./pants lint` to batch targets together for better performance, at the cost of less fine-grained caching. This can be disabled with `--fmt-per-target-caching` and `--lint-per-target-caching`.

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/1.26.x.rst) for a detailed change log.