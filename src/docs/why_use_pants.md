Why Use Pants?
==============
Pants was designed for large codebases that require a scalable
version control system and a build system that can perform fine-grained dependency management among thousands of code modules in a single source tree.
Pants was made for this type of usage in a way that other popular build tools, such as Ant, Maven, and SBT, were not. 

Pants is designed to give fast, consistent builds in a monorepo environment. Some noteworthy features include:

+ Fine-grained invalidation.
+ Shared build caches.
+ Concurrent task execution.
+ Incremental compilation.
+ Extensibility, via a plugin API.

Why Use a Monorepo?
------------------------
Monorepos have various advantages when it comes to scaling a codebase in a growing engineering organization. Many large engineering organizations prefer to keep their codebase in a single, large repo.

Having all the code in one place:

+ Increases code reuse.
+ Allows for easy collaboration between many authors.
+ Encourages a cohesive codebase where problems are refactored - not worked around.
+ Simplifies dependency management within the codebase. All of the code you run with is visible at a single commit in the repo.

But having such a large codebase presents challenges too. In particular, it requires a scalable version control system and a build system that can perform fine-grained dependency management among many thousands of code modules in a single source tree. Compiling with tools that have arbitrary recursively evaluated logic becomes painfully slow. Pants solves this issue by giving fast, consistent builds in an environment like this.

What Does Pants Support?
------------------------
Pants supports all stages of a typical build: tool bootstrapping, code generation, third-party dependency resolution, compilation, test running, linting, bundling and more.

Pants supports Java, Scala, Python, C/C++, Go, Thrift, Protobuf and Android code. Support for other languages, frameworks and code generators can be added by third party developers by authoring plugins through a well defined module interface.

Pants is modeled after Blaze, Google's internal build system, now open-sourced as [Bazel](http://bazel.io/). Another project with similar design goals to Pants is Facebook's [Buck](https://buckbuild.com/). Pants' development and feature set were informed by the needs and processes of many prominent software engineering organizations, including those at Twitter, Foursquare, Square, Medium and others. But it can also be used in smaller projects. Best of all, Pants is open source so you can freely share and modify Pants to suit your needs or distribute it to others when you want to share your own project.

How To Get Started
------------------------
+ [[Installing Pants|pants('src/docs:install')]]
+ [[Setting Up Pants|pants('src/docs:setup_repo')]]
+ [[Pants Concepts|pants('src/docs:first_concepts')]]
+ [[Tutorial|pants('src/docs:first_tutorial')]]
