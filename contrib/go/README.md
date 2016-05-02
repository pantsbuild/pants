# Go support for Pants

The Go plugin for Pants supports compilation and testing of Go code as well as third-party versioned dependency management without vendoring and other utilities to make working with existing go tooling easier.

## Installation

Go support is provided by a plugin distributed to [pypi](https://pypi.python.org/pypi/pantsbuild.pants.contrib.go).
Assuming you have already [installed pants](http://www.pantsbuild.org/install.html), you'll need to add the Go plugin in your `pants.ini`, like so:
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

## Codebase Requirements

// Single source root for src, seperate single for 3rdaprty

## Codebase setup and maintenance

// Seeding BUILD roots and buildgen.go goal
// 3rdparty pinning

## Building

You can build your code with `./pants compile [go targets]`. This will operate in a pants controlled (and hidden) workspace that knits together your local Go source with fetched, versioned third party code.

Since the workspaces constructed by pants internally for compilation are hidden, they aren't useful for retrieving final products. To surface a binary for use in deploys or ad-hoc testing you can `./pants binary [go binary targets]`. This will re-use any progress made by `./pants compile` in its Pants-controlled workspace and the binaries will be emitted under the `dist/go/bin/` directory by default.

## Testing

You can run your Go tests with `./pants test [go targets]`. Any [standard Go tests](https://golang.org/pkg/testing/) found amongst the targets will be compiled and run with output sent to the console.

## Working with other Go ecosystem tools

Go and the Go ecosystem provide rich tool support. From native Go tools like `go list` and `go vet` to editors like `vim` and Sublime that have plugins supporting Go symbol resolution and more. These tools all rely on a `GOROOT` and a `GOPATH` to know where to find binaries and code to operate against. Since pants controls the Go workspace these tools are unuseable without knowledge of the Pants-synthesized workspaces.  Enter the `./pants go` and `./pants go-env` goals.
// Actually explain go and go-env goals.
