# Plugin to support JS/Node

This is a plugin to integrate Node/NPM with Pants.

# Targets

You can specify node_remote_module targets referring to remote 3rd party Node modules, and
you can specify node_module targets defining projects in the source tree.

node_module targets can depend on node_remote_module targets in the "dependencies" field of
their specification in a BUILD file. A node_module target will work with a package.json
source file in the same directory, combining the BUILD dependencies with the additional fields from
the source package.json to form the complete package.json used for tasks on the target.

The way this currently works is, when resolving a target, Pants drops the dependencies,
devDependencies, peerDependencies and optionalDependencies fields from the target's corresponding
package.json file, and installs with a dependencies field populated from the BUILD file target
dependencies. This has the benefit of letting Pants work with an existing package.json file
for a project that can be installed via "npm install" without Pants.
However a project that takes advantage of this ability to be installed via a normal "npm install"
in the source tree would need its dependencies duplicated in the BUILD target and package.json file.
Obviously this is not desirable. Over time, Pants support for NPM should improve to work with a
fully functional package.json with no duplication of information in the BUILD file.

# Functionality

Utility is still limited right now.

## Node distribution bootstrapping

Pants will bootstrap itself with its own copy of Node and NPM and use them to run commands.
It runs those commands with the bootstrapped Node's bin directory at the front of the PATH.

## Resolve

Pants can install remote and local Node modules into the .pants.d working directory with
"./pants resolve [target]".

You can resolve node_remote_module and node_module targets. Pants effectively walks forward from
the edges of the dependency tree topological sort for a target and does an "npm install"
for each target it encounters along the way. node_module targets have their sources copied into
place under the working directory. node_remote_module dependencies are installed from the
remote source, and node_module dependencies are installed via paths to previously-installed targets
under the working directory.

## REPL

"./pants repl [target]" lets you run Node in REPL mode from the resolved target's path under the
working directory.

# Examples

The examples directory contains a few types of interdependent JS projects.

* A server project transpiled using Babel in its prepublish step
* A web build tool encapsulating Webpack and a set of loaders
* A web component (button) using React and CSS in a separate file, built with the web build tool,
  containing its own test file
* A web project using React, built with the web build tool, depending on the server project and
  button component, and containing its own test file

Resolving the server project produces a dist directory with code transpiled by Babel, in addition
to the project sources, in the target's directory under .pants.d.

The other projects are designed to eventually demonstrate building code with the web build tool
project via "npm run build" and testing (including a pre-test build step) via "npm test", once
the ability to run scripts from a target is implemented.
