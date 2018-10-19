# Plugin to support JavaScript and Node.js

This is a plugin to integrate Node.js with Pants.

# Targets

Node.js targets in pants are designed to work with existing Node.js package management tools. A node_module target will work with a package.json
source file in the same directory, combining the BUILD dependencies with the additional fields from the source package.json to form the complete
package.json used for tasks on the target.


`node_module`: A node module target.
`node_preinstalled_module`: A prebuilt node_module that will be downloaded during resolve step.
`node_bundle`: A bundle of node modules.
`node_remote_module`: Remote third party module. [Not recommended, instead specify dependencies in package.json with lock file]
`node_test`: Run Javascript tests defined in package.json.

# Functionality

There is limited support for `lint` and `fmt` that leverage the use of `eslint`. `eslint` global rules will need to be configured by the repo owner
and currently does not support target-level rule overrides.

## Source level dependencies

Source-level dependencies is currently supported within the `yarn` package manager. To specify a target-level dependency on
another node_module target, you must:

1. Specify the local dependency using the `file:` specifier following npm rules within the `package.json` with relative path
to the target dependency

2. The dependent target must have a valid target definition and package.json with the same package name as specified in the `file:` dependency

3. In the BUILD definition, the node_module target must also specify the fully qualified pants target address for each `file:` dependency.
(In the future, with dep inference, this step may no longer be necessary).

See the examples directory for real examples.

## Bootstrapping

Pants will bootstrap itself with its own copy of Node.js, NPM, and Yarn package manager and use them to run commands.
It runs those commands with the bootstrapped Node's bin directory at the front of the PATH.

Distribution versions can be modified in `pants.ini`.

## Package Management

There are two supported package management tools: NPM and Yarn. You can specify which package manager is used to `install`
your dependencies in your BUILD target definition.

NPM 5.0+ and Yarn both support locking dependencies to specific versions through the `package-lock.json` and `yarn.lock` files respectively.
To ensure determinism and reproducibility within Pants, these files should be checked into your repository and included in the the target definition.

## Resolve

Pants can install Node modules into the .pants.d working directory with

	`./pants resolve [target]`

You can resolve all types of node_module targets. Pants effectively walks forward from
the edges of the dependency tree topological sort for a target and does an "install"
for each target it encounters along the way. node_module targets have their sources copied into
place under the working directory. node_remote_module dependencies are installed from the
remote source, and node_module dependencies are installed via paths to previously-installed targets
under the working directory. Targets resolved into the .pants.d directory using the yarn package manager
will use the `--frozen-lockfile` parameter and will deterministically install your dependencies.

Pants can install Node modules into the source definition directory with

	`./pants node-install [target]`


## REPL

"./pants repl [target]" lets you run Node in REPL mode from the resolved target's path under the
working directory.

REPL is only working with npm package manager.

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

Resolving the server project produces a dist directory with code transpiled by Babel, in addition
to the project sources, in the target's directory under .pants.d.

The other projects are designed to eventually demonstrate building code with the web build tool
project via "npm run build" and testing (including a pre-test build step) via "npm test", once
the ability to run scripts from a target is implemented.

When Yarn package manager support was included, yarn projects have also been added.
