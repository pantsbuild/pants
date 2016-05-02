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

// Compile and binary goals

## Testing

// Test goal

## Working with other Go ecosystem tools

// The go-env and go goals (GOROOT/GOPATH)
