---
title: "2.0.x"
slug: "release-notes-2-0"
hidden: true
createdAt: "2020-06-26T03:30:39.353Z"
---
Some highlights:

- The v1 engine is being removed in order to focus on providing excellent support for v2 language backends: for now, this means Python.
- Dependencies can now be automatically inferred (with manual corrections where necessary), avoiding significant BUILD file boilerplate.
- Pants is now more file-centric and less target-centric. Targets exist to apply metadata to files, but the unit of operation in most cases is a file. In particular, dependency inference happens at the file level.
- The dynamic UI now outputs results for `test`, `lint`, and `fmt` as soon as it has them, rather than waiting for everything to finish.
- Added MyPy support. See [typecheck](doc:python-typecheck-goal).
- Added Python Coverage support. See [test](doc:python-test-goal).
- `help` now outputs the current value and the derivation of that value. This replaces the `options` goal.
- Added gRPC and MyPy Protobuf support. See [Protobuf](doc:protobuf).

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/2.0.x.rst) for a detailed change log.

See [How to upgrade](doc:how-to-upgrade-pants-2-0) for a guide on upgrading from Pants 1.x to 2.0.