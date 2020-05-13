# Pants Build System

Pants is a scalable build system for _monorepos_: codebases containing 
multiple projects, often using multiple programming languages and frameworks, 
in a single unified code repository.

Some noteworthy features include:

* Explicit dependency modeling.
* Fine-grained invalidation.
* Shared result caching.
* Concurrent execution.
* Remote execution.
* Unified interface for multiple tools and languages.
* Extensibility and customizability via a plugin API.

Documentation:

 * V2 version of Pants (Python only, for now): https://pants.readme.io/docs/welcome-to-pants
 * V1 version of Pants: http://www.pantsbuild.org/

We release to [PyPI](https://pypi.org/pypi)
[![version](https://img.shields.io/pypi/v/pantsbuild.pants.svg)](https://pypi.org/pypi/pantsbuild.pants)
[![license](https://img.shields.io/pypi/l/pantsbuild.pants.svg)](https://pypi.org/pypi/pantsbuild.pants)

We use [Travis CI](https://travis-ci.org) to verify the build
[![Build Status](https://travis-ci.com/pantsbuild/pants.svg?branch=master)](https://travis-ci.com/pantsbuild/pants/branches).

# Requirements

To run Pants, you need:

* Linux or macOS.
* Python 3.6+ discoverable on your `PATH`.
* A C compiler, system headers, Python headers (to compile native Python modules) and the `libffi`
 library and headers (to compile and link modules that use CFFI to access native code).
* Internet access (so that Pants can fully bootstrap itself).

Additionally, if you use the JVM backend to work with Java or Scala code:

* OpenJDK or Oracle JDK version 8 or greater.
