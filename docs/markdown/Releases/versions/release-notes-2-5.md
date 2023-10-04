---
title: "2.5.x"
slug: "release-notes-2-5"
hidden: true
createdAt: "2021-04-02T19:04:13.658Z"
---
Some highlights:

* Adds Shell support, specifically for Shellcheck, shfmt, and shUnit2. See [Shell overview](doc:shell).
* Allow skipping linters/formatters/typecheckers on a per-target basis, e.g. with `skip_black=True`. See [Linters and formatters](doc:python-linters-and-formatters).
* Pants will now autodiscover config files for tools. See [Linters and formatters](doc:python-linters-and-formatters).
* When you use a constraints file, Pants now knows how to resolve your dependencies only once, and then extract the subset of your dependencies from that single resolve.
    * This change means that you will not need to resolve dependencies as many times when running `./pants package`.
    * Cache keys are also smaller for goals like `./pants test` and `./pants lint`, which means changing your constraints.txt is less likely to invalidate your whole cache.
* Support for running Pants using Python 3.9.

See [here](https://github.com/pantsbuild/pants/blob/main/src/python/pants/notes/2.5.x.md) for a detailed change log.