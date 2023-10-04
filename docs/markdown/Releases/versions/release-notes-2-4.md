---
title: "2.4.x"
slug: "release-notes-2-4"
hidden: true
createdAt: "2021-02-28T01:52:21.946Z"
---
Some highlights:

* Added opt-in [anonymous telemetry](https://www.pantsbuild.org/v2.4/docs/anonymous-telemetry), to provide the Pants maintainers with data to help drive development decisions.
* Added a warning when an inferred dependency is [skipped due to ambiguity](https://github.com/pantsbuild/pants/pull/11792), and allowed ambiguity to be resolved by explicitly including or excluding (with `!`) dependency choices.
* Enabled use of [pytest-html](https://pypi.org/project/pytest-html/), and other Pytest plugins that write output to files.
* Added support for Pytest config files (e.g. `pytest.ini`). See [test](doc:python-test-goal).
* Added a `--stats-log` option for insights on cache behavior at the end of the run, such as the # of cache hits.
* Added a [default `module_mapping`](https://github.com/pantsbuild/pants/issues/11634) for Python 3rdparty dependency inference.
* Fixed an issue that would prevent code-generated sources from having valid source roots.

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/2.4.x.md) for a detailed change log.