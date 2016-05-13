# Go support for Pants

The Go plugin for Pants supports compilation and testing of Go code as well as third-party versioned
dependency management without vendoring, and other utilities to make working with existing go
tooling easier.

## Installation

Go support is provided by a plugin distributed to [pypi]
(https://pypi.python.org/pypi/pantsbuild.pants.contrib.go).
Assuming you have already [installed pants](http://www.pantsbuild.org/install.html), you'll need to
add the Go plugin in your `pants.ini`, like so:
```ini
[GLOBAL]
pants_version: 1.0.0

plugins: [
    'pantsbuild.pants.contrib.go==%(pants_version)s',
  ]
```

On your next run of `./pants` the plugin will be installed and you'll find these new goals:
```
./pants goals
Installed goals:
...
      go: Runs an arbitrary go command against zero or more go targets.
  go-env: Runs an arbitrary command in a go workspace defined by zero or more go targets.
...
```

## Codebase requirements
Pants aims to control your Go workspace to provide guarantees of pinned 3rdparty dependencies (much
as tools like [GoDep](https://github.com/tools/godep)) and proper change invalidation. In order to
do this, there are a few requirements on your code layout and a few changes you'll need to make in
your Go development workflow.

Pants requires:

1. You have one Go source tree.
2. You tell Pants about your Go source code packages using BUILD file targets.
3. You declare 3rdparty dependencies in BUILD files that pin the version of the dependency.

You likely comply with 1 already, the Go standards push almost all projects in this direction, but 2
and 3 may be new concepts if you haven't used Pants or a tool like it before. You may want to read
up on [BUILD files](/src/docs/build_files.md) and the [3rdparty pattern](/src/docs/3rdparty.md)
before continuing.

## Codebase setup

Pants has tooling to help maintain your Go BUILD files, but it needs some configuration and seeding
to work.

### Source root configuration

Internally, pants uses the concept of a "source root" to determine the portion of a source file's
path that represents the package for the language in question. For Go code in a standard layout, the
source root is `$GOPATH/src`, but pants may not guess this correctly. Suppose we're setting up Pants
for a multi-language repo layed out with Java code under `src/java/com/yourcompany/...` and Go code
under `src/go/src/...`. You can inspect Pants' source root guesses for this layout with:
```
./pants roots
src/go: go
src/java: java
```

In this example the Java guess is correct but the Go guess is not, we need `src/go/src`. We can
explicitly set the source root for Go with this addition to `pants.ini`:
```ini
[source]
source_roots: {
    'src/go/src': ['go']
  }
```

This tells pants that the `src/go/src` source root houses one type of code, Go code. We can verify
the setting:
```
./pants roots
src/go/src: go
src/java: java
```

Unless your Go code has no 3rdparty dependencies, we also need to seed a source root where 3rdparty
dependency version information can be stored. We can seed this with `mkdir -p 3rdparty/go` and check
Pants knowledge of the new source root:
```
src/go/src: go
src/java: java
3rdparty/go: go
```

### BUILD seeding

You'll need to write minimal BUILD files for all the root binaries and libraries you intend to
build. For each binary, just place a BUILD file in the `main`'s package dir with contents
`go_binary()`. Likewise, for libraries you'll need a BUILD file with contents `go_library()`. You
might even automate this by running the following from the root of your Go source tree:
```bash
GOPATH=$PWD go list -f '{{.Dir}} {{.Name}}' ./... | while read dir name
do
  if [[ "${name}" == "main" ]]
  then
    echo "go_binary()" > "${dir}/BUILD"
  else
    echo "go_library()" > "${dir}/BUILD"
  fi
done
```

### Dependency metadata generation

Now that we have roper source root configuration and skeleton BUILD files, we can proceed to
auto-generate the dependency information pants needs from BUILD files using the `buildgen` goal.
Here we set options to emit the BUILD files to disk, include 3rdparty remote dependency BUILD
files, and fail if any 3rdparty dependencies have un-pinned versions:
```
./pants buildgen.go --materialize --remote --fail-floating
...
12:43:08 00:00   [buildgen]
12:43:08 00:00     [go]..
                       src/go/src/server/BUILD (server)
                       3rdparty/go/github.com/gorilla/mux/BUILD (github.com/gorilla/mux) FLOATING
                   Un-pinned (FLOATING) Go remote library dependencies are not allowed in this repository!
                   Found the following FLOATING Go remote libraries:
                       3rdparty/go/github.com/gorilla/mux/BUILD (github.com/gorilla/mux) FLOATING
                   You can fix this by editing the target in each FLOATING BUILD file listed above to include a `rev` parameter that points to a sha, tag or commit id that pins the code in the source repository to a fixed, non-FLOATING version.
FAILURE: Un-pinned (FLOATING) Go remote libraries detected.
```
The output shows one local target was (re)generated and one 3rdparty target was generated, but with
no version picked.

The local target now looks like:
```
cat src/go/src/server/BUILD
# Auto-generated by pants!
# To re-generate run: `pants buildgen.go --materialize --remote`

go_binary(
  dependencies=[
    '3rdparty/go/github.com/gorilla/mux',
  ]
)
```

And the 3rdparty target:
```
cat 3rdparty/go/github.com/gorilla/mux/BUILD
# Auto-generated by pants!
# To re-generate run: `pants buildgen.go --materialize --remote`

go_remote_library()
```

To fix the `FLOATING` version error we can edit like so:
```diff
git diff -U1 3rdparty/go/github.com/gorilla/mux/BUILD
diff --git a/3rdparty/go/github.com/gorilla/mux/BUILD b/3rdparty/go/github.com/gorilla/mux/BUILD
index 5d283d4..38ed297 100644
--- a/3rdparty/go/github.com/gorilla/mux/BUILD
+++ b/3rdparty/go/github.com/gorilla/mux/BUILD
@@ -3,2 +3,2 @@

-go_remote_library()
+go_remote_library(rev='v1.1')
```
Here we've used the `v1.1` tag of the `github.com/gorilla/mux` project, but we could also use a sha
or branch name (not reccomended since branches can float).

Re-running buildgen finds success:
```
./pants buildgen.go --materialize --remote --fail-floating
...
12:53:27 00:00   [buildgen]
12:53:27 00:00     [go]..
                       src/go/src/server/BUILD (server)
                       3rdparty/go/github.com/gorilla/mux/BUILD (github.com/gorilla/mux) v1.1
12:53:27 00:00   [complete]
               SUCCESS
```

A compile fails though!:
```
$ ./pants binary ::
...
22:44:57 00:00   [resolve]
22:44:57 00:00     [ivy]
22:44:57 00:00       [cache]
22:44:57 00:00       [bootstrap-nailgun-server]
22:44:57 00:00     [go]
22:44:57 00:00       [cache]
                   No cached artifacts for 1 target.
                   Invalidated 1 target.INFO] Downloading https://github.com/gorilla/mux/archive/v1.1.tar.gz...

22:45:00 00:03       [github.com/gorilla/mux]WARN] Injecting dependency from BuildFileAddress(BuildFile(3rdparty/go/github.com/gorilla/mux/BUILD, FileSystemProjectTree(/home/jsirois/dev/pantsbuild/issues-3417)), mux) on 3rdparty/go/github.com/gorilla/context:context, but the dependency is not in the BuildGraph.  This probably indicates a dependency cycle, but it is not an error until sort_targets is called on a subgraph containing the cycle.

                   3rdparty/go/github.com/gorilla/mux has remote dependencies which require local declaration:
                    --> github.com/gorilla/context (expected go_remote_library declaration at 3rdparty/go/github.com/gorilla/context)
FAILURE: Failed to resolve transitive Go remote dependencies.
```

Here we see a failure resolving the transitive 3rdparty `github.com/gorilla/context` dependency that
our explicit dependency on `github.com/gorilla/mux` requires. The lesson here is that `buildgen`
doesn't attempt to resolve or compile code, it only operates on code and BUILD files already on
disk. We can proceed though by following the instructions in the resolve failure:
```
mkdir -p 3rdparty/go/github.com/gorilla/context
echo "go_remote_library()" > 3rdparty/go/github.com/gorilla/context/BUILD
```

Since we have not picked a version for this new (transitive) dependency, `buildgen` will fail,
asking us to pick one:
```
./pants buildgen.go --materialize --remote --fail-floating
...
22:45:52 00:00   [buildgen]
22:45:52 00:00     [go].
                    3rdparty/go/github.com/gorilla/mux/BUILD (github.com/gorilla/mux) v1.1
                    3rdparty/go/github.com/gorilla/context/BUILD (github.com/gorilla/context) FLOATING
                    src/go/src/server/BUILD (src/server)
                   Un-pinned (FLOATING) Go remote library dependencies are not allowed in this repository!
                   Found the following FLOATING Go remote libraries:
                    3rdparty/go/github.com/gorilla/context/BUILD (github.com/gorilla/context) FLOATING
                   You can fix this by editing the target in each FLOATING BUILD file listed above to include a `rev` parameter that points to a sha, tag or commit id that pins the code in the source repository to a fixed, non-FLOATING version.
FAILURE: Un-pinned (FLOATING) Go remote libraries detected.


22:45:53 00:01   [complete]
               FAILURE
```

And at this point we are back on familiar ground.  We can edit
`3rdparty/go/github.com/gorilla/context/BUILD` and provide a version and repeat `compile` and
`buildgen` until we have a fully pinned, explicit 3rparty dependency set and compiling codebase.
At this point the generated BUILD files can be checked in.

## Codebase maintenance

When new packages are added or existing packages' dependencies are modified a similar seeding (only
needed if the packages are new roots), buildgen and compilation can be cycled through. To simplify
the process it's recommended the flags be made defaults for the repo by editing your pants init to
include the following section:
```ini
[buildgen.go]
# We always want buildgen to materialize BUILD files on disk as well as handle seeding remotes
# when new ones are encountered.  We also never want to allow FLOATING revs, they should be pinned
# right away.
materialize: True
remote: True
fail_floating: True
```
Now running buildgen is just `./pants buildgen`.

## Building

You can build your code with `./pants compile [go targets]`. This will operate in a pants controlled
(and hidden) workspace that knits together your local Go source with fetched, versioned third party
code.

Since the workspaces constructed by pants internally for compilation are hidden, they aren't useful
for retrieving final products. To surface a binary for use in deploys or ad-hoc testing you can
`./pants binary [go binary targets]`. This will re-use any progress made by `./pants compile` in its
Pants-controlled workspace and the binaries will be emitted under the `dist/go/bin/` directory by
default.

## Testing

You can run your Go tests with `./pants test [go targets]`. Any [standard Go tests]
(https://golang.org/pkg/testing/) found amongst the targets will be compiled and run with output
sent to the console.

## Working with other Go ecosystem tools

Go and the Go ecosystem provide rich tool support. From native Go tools like `go list` and `go vet`
to editors like `vim` and [Sublime](https://www.sublimetext.com/) that have plugins supporting Go
symbol resolution and more. These tools all rely on a `GOROOT` and a `GOPATH` to know where to find
binaries and code to operate against. Since pants controls the Go workspace these tools are
unuseable without knowledge of the Pants-synthesized workspaces.  The `./pants go` and
`./pants go-env` goals can help use or integrate with these tools.

### go

The `./pants go` command can be considered the equivalent of running `go` with a few differences.
This is particularly useful when Pants doesn't provide a goal that maps to the `go` command you
already know you want to run.

Running the command with no extra arguments is instructive:
```
./pants go

FAILURE: The pants `{goal}` goal expects at least one go target and at least one pass-through argument to be specified, call with:
  ./pants go [missing go targets] -- [missing pass-through args]


FAILURE
```
So, where you might run `go list -f '{{.Imports}}' server` to list the server package's imports, you'd instead run:
```
./pants go src/go/src/server -- list -f '{{.Imports}}'
[fmt github.com/gorilla/mux html net/http]
```

Currently, although Pants checks go formatting via the `checkstyle` goal, it doesn't offer a way to
automatically fix formatting. You can work around the lack of Pants support for re-formatting via the
following:
```
./pants go src/go:: -- fmt ./...
```

### go-env

The `./pants go-env` is useful for setting the environment some other binary runs in. If you use
Sublime for example, its Go plugins tend to respect the `GOROOT` and `GOPATH` environment variables
as the default configuration for said same (vs manual plugin configuration). To run Sublime against
your Pants-managed Go binary and `GOPATH`, just:
```
./pants go-env src/go/src/server -- subl .
```
You'll find that, for example, [GoSublime](https://github.com/DisposaBoy/GoSublime) will be able to
browse to both local code symbols, 3rdparty Pants-fetched code symbols, and Go std lib symbols in
the Pants-controlled Go distribution.

As a sanity check you can see exactly what is exported:
```
./pants go-env src/go/src/server -- set | grep -E ^GO
GOPATH=/home/jsirois/dev/pantsbuild/jsirois-pants2/.pants.d/go-env/go-env/src.server
GOROOT=/home/jsirois/.cache/pants/bin/go/linux/x86_64/1.6.2/unpacked/go
```
