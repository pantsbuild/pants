Why Use Pants?
==============

If you work in an large engineering environment with a codebase shared
between many teams, you have a lot of code!  Over time, your codebase
will consist of many interrelated projects and libraries.

The choice of how you organize your code has many implications.  If
you have a large number of small, independently-versioned code
repositories, each project will have a small, manageable codebase but
what about all the code it depends on?

+ How do you find and modify the code your project depends on?
+ If you are a library developer, how and when will applications adopt
your most recent changes?
+ If you are a product developer, how and when will you upgrade your
  library dependencies?
+ Whose job is it to verify that changes don't break other projects
  that depend on them?

In short, when working with many small code repositories the
dependency problem can become intractable.

Many large engineering organizations prefer to keep their codebase in
a single, large repo.  Such a codebase is sometimes referred to as a
_monorepo_.  Monorepos have various advantages when it comes to
scaling a codebase in a growing engineering organization.

 Having all the code in one place:

+ Increases *code reuse*.
+ Allows for *easy collaboration* between many authors.
+ Encourages a *cohesive codebase* where problems are refactored - not worked around.
+ Simplifies *dependency management* within the codebase.   All of the
code you run with is visible at a single commit in the repo.

But having such a large codebase presents challenges too.    In
particular, it requires a scalable version control system and a build
system that can perform fine-grained dependency management among many
thousands of code modules in a single source tree.  Compiling with
tools that have arbitrary recursively evaluated logic becomes
painfully slow.

Pants was designed for this type of usage in a way that other popular build tools, such as
Ant, Maven, and SBT, were not. Pants is designed to give fast,
consistent builds in a monorepo environment.  Some noteworthy features
include:

+ Fine-grained invalidation.
+ Shared build caches.
+ Concurrent task execution.
+ Incremental compilation.
+ Extensibility, via a plugin API.

Pants supports all stages of a typical build: tool bootstrapping, code
generation, third-party dependency resolution, compilation, test
running, linting, bundling and more.

Pants supports Java, Scala, Python, C/C++, Go, Thrift, Protobuf and Android code.
Support for other languages, frameworks and code generators can
be added by third party developers by authoring plugins through a well
defined module interface.

Pants is modeled after Blaze, Google's internal build system, now open-sourced as [Bazel](http://bazel.io/).
Another project with similar design goals to Pants is Facebook's [Buck](https://buckbuild.com/).
Pants' development and feature set were informed by the needs and
processes of many prominent software engineering organizations,
including those at Twitter, Foursquare, Square, Medium and others.
But it can also be used in smaller projects.  Best of all, Pants is
open source so you can freely share and modify Pants to suit your
needs or distribute it to others when you want to share your own
project.
