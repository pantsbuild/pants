Why Use Pants?
==============

One of the most complex tasks in large codebases is dependency management.
If you have a large number of small, independently-versioned code repositories,
the dependency problem can become intractable.

In many cases a single, large repo is a preferable architecture for your codebase.
It increases code reuse, collaboration and cohesion, especially in large engineering
organizations.

A codebase with at least some of these properties is sometimes referred to as a _monorepo_.  Monorepos
have various advantages when it comes to scaling a codebase in a growing engineering organization.

However, building code in a monorepo requires a build system design for that purpose. In particular,
it requires a build system that can perform fine-grained dependency management among many thousands
of code modules in a single source tree.

Pants was designed for this type of usage in a way that other popular build tools, such as
Ant, Maven, and SBT, were not. Some noteworthy features include:

+ Fine-grained invalidation.
+ Shared build caches.
+ Concurrent task execution.
+ Incremental compilation.
+ Extensibility, via a plugin API.


Pants supports all stages of a typical build: tool bootstrapping, code generation, third-party dependency
resolution, compilation, test running, linting, bundling and more.

Pants supports Java, Scala, Python, C/C++, Go, Thrift, Protobuf and Android code.
Adding support for other languages, frameworks and code generators is straightforward.

Pants is modeled after Blaze, Google's internal build system, now open-sourced as [Bazel](http://bazel.io/).
Another project with similar design goals to Pants is Facebook's [Buck](https://buckbuild.com/).
Pants' development and featureset were informed by the needs and processes of many prominent software engineering
organizations, including those at Twitter, Foursquare, Square, Medium and more.
