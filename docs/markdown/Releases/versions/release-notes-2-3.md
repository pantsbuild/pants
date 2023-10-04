---
title: "2.3.x"
slug: "release-notes-2-3"
hidden: true
createdAt: "2021-01-11T01:11:31.324Z"
---
Some highlights:

* Improved performance when running Python subprocesses like Pytest, Flake8, and MyPy, thanks to Pex's new `venv` mode. This shaved off around 1 second for test runs in benchmarks!
* `./pants tailor` goal, which will auto-generate BUILD files for you. See [Adopting Pants in existing repositories](doc:existing-repositories).
* Support for specifying `file://` URLs [for downloaded tools](https://github.com/pantsbuild/pants/pull/11499) like Pex and Protoc.
* More robust remote caching support. The client should be more stable and should avoid performance slowdowns thanks to some new optimizations. See [Remote Execution](doc:remote-execution).

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/2.3.x.md) for a detailed change log.