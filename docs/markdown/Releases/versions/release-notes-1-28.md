---
title: "1.28.x"
slug: "release-notes-1-28"
hidden: true
createdAt: "2020-05-05T16:51:04.132Z"
---
Some highlights:

- Added support for generating Python from Protocol Buffers (Protobuf). See [Protobuf](doc:protobuf).
- Added the `junit_xml_dir` option to the `[pytest]` scope to allow saving JUnit XML test results. See [test](doc:python-test-goal).
- Allow defining macros though a new "preludes" mechanism. See [Macros](doc:macros).
- Simplified how source roots are declared. See [Source roots](doc:source-roots).
- Added the `dependees` goal. See [Project introspection](doc:project-introspection).
- UI enhancements, including:
    - Improved the interactive UI to not take over the screen and to work when piping to other programs.
    - Improved output for `fmt` and `lint` to explain which tools ran.
    - Improved output for `test` to be less chatty.

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/1.28.x.rst) for a detailed change log.