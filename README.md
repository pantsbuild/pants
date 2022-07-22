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

Documentation: [www.pantsbuild.org](https://www.pantsbuild.org/).

# Requirements

To run Pants, you need:

* Linux or macOS.
* Python 3.7+ discoverable on your `PATH`.
* A C compiler, system headers and Python headers (to compile native Python modules).
* Internet access (so that Pants can fully bootstrap itself).

# Credits

We release to [PyPI](https://pypi.org/pypi)

[![version](https://img.shields.io/pypi/v/pantsbuild.pants.svg)](https://pypi.org/pypi/pantsbuild.pants)
[![license](https://img.shields.io/pypi/l/pantsbuild.pants.svg)](https://pypi.org/pypi/pantsbuild.pants)

<img width="150" height="61" src="https://uploads-ssl.webflow.com/5ac3c046c82724970fc60918/5c019d917bba312af7553b49_MacStadium-developerlogo.png">
