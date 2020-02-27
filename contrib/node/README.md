# Node.js Support

This is a plugin to integrate Node.js with Pants.

# Targets

Node.js targets in Pants are designed to work with existing Node.js package management tools and
their configuration files. The node_module target type uses a package.json file in the same
directory as its definition. It combines dependencies declared on the target in the BUILD
file with the original package.json to form a complete package.json that can be used to run tasks
on the target through Pants.


* `node_module`: A node module target.
* `node_preinstalled_module`: A prebuilt node_module that will be downloaded during resolve step.
* `node_bundle`: A bundle of node modules.
* `node_remote_module`: Remote third party module. [Not recommended, instead specify dependencies in package.json with lock file]
* `node_test`: Run Javascript tests defined in package.json.

# Functionality

There is limited support for linting and formatting using the `lint` and `fmt` goals, which use `eslint`.
`eslint` global rules will need to be configured by the repo owner

## Source level dependencies

Source-level dependencies are currently supported within the `yarn` package manager. To specify a target-level dependency on
another node_module target, you must:

1. Specify the local dependency using the `file:` specifier following npm rules within the `package.json` with relative path
to the target dependency

2. The dependent target must have a valid target definition and package.json with the same package name as specified in the `file:` dependency

3. In the BUILD definition, the node_module target must also specify the fully qualified pants target address for each `file:` dependency.
(In the future, with dep inference, this step may no longer be necessary).

4. Scopes normally defined in the the `name` field of the `package.json` file needs to be replicated in the BUILD definition in the `node_scope` option.

With some caveats,

* Peer dependencies cannot be resolved within source dependencies. The source dependencies are symlinked and do not have a direct relationships with the parent
target. There may be duplicate dependencies since there is no flattening of the dependency graph.

* Source dependencies can only be specified in the “dependencies” field.

* Source dependencies need to match 1:1 with package dependencies, but cannot currently express the node_scope within that context. The node_scope is assumed through the `node_scope` field in the BUILD definition.

See the examples directory for real examples.

## Bootstrapping

Pants will bootstrap itself with its own copy of Node.js, NPM, and Yarn package manager and use them to run commands.
It runs those commands with the bootstrapped Node's bin directory at the front of the PATH.

Distribution versions can be modified in `pants.toml`.

## Package Management

There are two supported package management tools: NPM and Yarn. You can specify which package manager is used to `install`
your dependencies in your BUILD target definition.

NPM 5.0+ and Yarn both support locking dependencies to specific versions through the `package-lock.json` and `yarn.lock` files respectively.
To ensure determinism and reproducibility within Pants, these files should be checked into your repository and included in the
target definition's sources argument.

## Install

Pants can install Node modules into the source definition directory with

    ./pants node-install [target]

You can install all types of node_module targets. Pants effectively walks forward from
the edges of the dependency tree topological sort for a target and does an "install"
for each target it encounters along the way. Pants then symlinks each of the source dependencies
in the correct path under the `node_modules` directory.

## Test

Pants can run tests defined in your `package.json` file similar to your vanilla package manager.
The main difference is that the tests are executed within Pants' virtual environment.

`node_test` targets are able to run scripts defined in the `package.json` file.

When Pants executes a `node_test` target, the target's sources are copied into place under the working directory. The
sources are then `resolved` or `installed` into the pants working directory. The targets and paths are cached
and passed into the Node.js runtime as NODE_PATH parameters to execute your test.

Resolve is a task that helps Pants install and keep track of node_module targets.

`node_remote_module` dependencies are installed from the remote source, and `node_module` dependencies are installed via
paths to previously-installed targets under the working directory.


## REPL

`./pants repl [target]` lets you run Node in REPL mode from the resolved target's path under the
working directory.

REPL only works with npm package manager.

# Examples

The examples directory contains a few types of interdependent JS projects.

* A server project transpiled using Babel in its prepublish step
* A web build tool encapsulating Webpack and a set of loaders
* A web component (button) using React and CSS in a separate file, built with the web build tool,
  containing its own test file
* A web project using React, built with the web build tool, depending on the server project and
  button component, and containing its own test file
* A yarn workspace project using source-level dependencies in two ways. (Workspaces and pants).
  Source-level dependencies does not need Yarn Workspaces.
