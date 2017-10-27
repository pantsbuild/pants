Strict Dependencies
===================

### What is strict_deps?

Historically, Pants works with transitive dependencies. This means that in
order to compile each target, the compiler must scan that full transitive set.
But, most targets do not need access to all of their transitive dependencies at
compile time. We can make compilation faster if we can reduce those compile
dependencies to just the necessary ones.

Strict_deps is a Pants feature that changes compile behavior so that only
direct dependencies and exports are included on the compile classpath for a
target. This reduces scalac times by reducing the amount of class files scalac
needs to scan before beginning a compile. It improves cache hit rates by
reducing the number of files that are included in each target’s compile cache
key.eat

### Why strict_deps?

Use of strict_deps improves cache hit rates and per-target compilation time
(on the order of 10-20%).

Example
-------

With strict_deps enabled, we can identified some gaps between what the
compiler expects on a classpath and what is actually available on the
classpath as specified in BUILD files.

Let's look at a simple example involving 3 targets A, B and C. B depends on A,
and C depends on B. Thus their dependency graph can be represented like this:
C->B->A. Their declarations in BUILD file are shown as below:

    :::python
    scala_library(
        name='A',
        source=['A.scala'],
    )

    scala_library(
        name='B',
        source=['B.scala'],
        dependencies=[':A'],
    )

    scala_library(
        name='C',
        source=['C.scala'],
        dependencies=[':B'],
    )

If we compile C with strict_deps turned off, everything works fine, as all
transitive dependencies of C will be added to compile time classpaths.
However, the compilation may require additional dependencies if strict_deps
is turned on. With strict_deps=True, only B is in C's compile time classpath.
There are 2 cases for the failure.

1. C directly uses APIs from A. This is obviously a mistake by author of C,
and the fix is simple, just add A to C's dependency list.

2. C does not use APIs from A, but compiler still wants A to be in C's
classpaths. This is tricky, as author of C may not even be aware of A. It's
hard for C's author to get the right dependency list in this case.

People may wonder why compiler asks for A to compile C in the first place.
Unfortunately this is a limitation for both javac and scalac. This is just
how these compilers behave.

Strict_deps for Library Developers
----------------------------------

The compile overhead of a library change for downstream targets when
strict_deps is enabled should be minimized to just the targets that
depend directly on the library target or depend on a target that exports
that target.

### Invalidation

This is a change from the current behavior where all downstream targets will
have their compile invalidated.

With strict_deps, a change to a library target will only invalidate the
compile artifacts of dependent targets if they have
1. A direct dependency on the changed library target, or
2. A dependency on it via the export graph.

Before, if a target depending on a library had an implicit dependency on a
transitive dependency of the library target it would just work. The transitive
dependency would end up on the dependent target’s compile classpath and that
target would compile happily. Strict deps removes that implicit transitivity,
which exposes undeclared dependencies.

This introduces two new sources of errors.
1. When adding a new library dependency to a target, if the library dependency
requires some of its dependencies to be on the compile classpath, the compile
can fail if those dependencies don’t make it on the classpath. These errors
are a bit weird and will be confusing at first.
2. When a library target adds a new publicly visible dependency, targets that
depend on the library target will fail to compile with the same kind of error
message as 1.

Errors, Exports, and Missing-deps-suggest
-----------------------------------------

The errors sometimes have different messages, but usually in Scala they look
something like this:

    :::bash
    [error] <path-to-current-sources>/<Some-file>.scala:71:32: Symbol 'type <Some-type>' is missing from the classpath.
    [error] This symbol is required by '<Some-other-type>.timeout'.
    [error] Make sure that type <Some-type>is in your classpath and check for conflicting dependencies with `-Ylog-classpath`.
    [error] A full rebuild may help if <Some-other-type>.class' was compiled against an incompatible version of <none>.<Some-type>.
    [error]         Some-file.code
    [error]

**NOTE: It's likely the source snippet may not be related to the error**

There are two possible solutions for this error. One is to identify the
dependency that is missing and add it to your target directly.

### Missing-deps-suggest

Missing-deps-suggest is a feature that will try to identify the target that
failed to compile and suggest a dependency that may be missing.

If this doesn't provide a solution, then the second solution to this error
is exporting the missing type's target in the dependency you depend on.

### Exports

Exports reintroduce limited transitivity to the dependencies provided at
compile time. When a target exports one of its dependencies, that dependency
will be on the classpath of any target that depends on it.

#### How to Solve An Error With Exports

There are three targets that need to be identified to fix an error like this:

1. the target that failed to compile.
2. the dependency of 1 that owns the type that needed the missing type
3. the dependency of target 2 that owns the missing type.

Let's look at an example failure:

    :::bash
    [1/1] Compiling 1 zinc source in 1 target (examples/src/scala/org/pantsbuild/example/strictdeps:h).
    17:12:58 00:03       [compile]

    17:12:58 00:03         [zinc]
                            [error] Symbol 'type z.Z' is missing from the classpath.
                            [error] This symbol is required by 'method z.X.yyy'.
                            [error] Make sure that type Z is in your classpath and check for conflicting dependencies with `-Ylog-classpath`.
                            [error] A full rebuild may help if 'X.class' was compiled against an incompatible version of z.
                            [error] one error found
                            [error] Compile failed at Sep 19, 2017 5:12:59 PM [0.916s]

    17:12:59 00:04         [missing-deps-suggest]

                        compile(examples/src/scala/org/pantsbuild/example/strictdeps:h) failed: Zinc compile failed.
    FAILURE: Compilation failure: Failed jobs: compile(examples/src/scala/org/pantsbuild/example/strictdeps:h)

Target 1 should be the most straight-forward to find. It's the target named in
the failure message as a failed job. It's mentioned both at the end of the
failing compile, in the line starting with FAILURE: Compilation failure, and
in a line near the error message. In this example, the failure is
compile(examples/src/scala/org/pantsbuild/example/strictdeps:h). So, target 1
is examples/src/scala/org/pantsbuild/example/strictdeps:h.

Finding target 2 involves looking at target 1's dependencies and figuring out
which one contains the type from the error message. First, let's find the
type. In a message like this, target 2's type is the one that required the
missing type. In this message specifically, it's the following line:

    :::bash
    [error] This symbol is required by 'method z.X.yyy'.

The type from target 2 is the method yyy on z.X. How to we find the target
for that type? One way would be to eyeball it. Let's look at the BUILD file.

    :::python
    scala_library(
        name='h',
        sources=['H.scala'],
        dependencies=[':x'],
        strict_deps=True
    )

In this example, target 1 only has one dependency, x. That makes finding
target 2 easy. It's :x.

Now that we know target 1 and target 2, let's find 3. Since we're doing this
manually, we'll look at the build files again.

Here's target 2's BUILD file declaration:

    :::python
    scala_library(
        name='x',
        sources=['X.scala'],
        dependencies=[':z']
    )

It too has only one dependency, so we know what Target 3 is. It's :z.

Now that we know what the missing dependency is, we can fix the error.
Z has to be on the classpath in order to use X, so any target depending
on :x will also need :z. We could just add a dependency on :z to :h, but
doing so would result in new users of :x running into this same error. To
prevent that, let's add an export to :x of :z.

    :::python
    scala_library(
        name='x',
        sources=['X.scala'],
        dependencies=[':z'],
        exports=[':z']
    )

Now our target compiles successfully.
