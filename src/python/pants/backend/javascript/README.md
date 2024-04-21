# Javascript backend

This README is mainly for understanding the current backend functionality for PR review purposes. 
Plan to migrate much of this content to user docs.

## Definitions

- Module: A single javascript source file. See https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules
- Package: A javascript directory (or file) described by a `package.json` file. See https://docs.npmjs.com/about-packages-and-modules
- Workspaces: Functionality of package managers for supporting development of multiple packages in a single repository
  - In [npm](https://docs.npmjs.com/cli/v7/using-npm/workspaces) and [yarn](https://classic.yarnpkg.com/lang/en/docs/workspaces/), a "workspaces" key is added to a top level `package.json` file, which points to child packages. 
    - A single 'workspace' and 'package' have the same root directory, however, 'workspace' has an additional meaning in that package managers allow you to execute commands in the context of a workspace.
    - The term 'workspace' (as singular) is not frequently used though.
  - In [pnpm](https://pnpm.io/workspaces), a 'workspace' is defined by a `pnpm-workspace.yaml` file which points to child packages.
    - i.e., a single workspace is linked to multiple child packages, unlike in the definition from npm and yarn. This is only trivial for our purposes, but worth keeping in mind when talking about workspaces.
- Project: Not formally defined. It is often used informally to refer to packages (e.g. where a single package might be a React project). 
  - In this backend, `ProjectEnvironment` is used to indicate the context (package + configuration) in which a node process is run. This could be inside a singular package directory, or a root package.json defining workspaces, or a directory containing a `pnpm-workspace.yaml` file. 

## Example repository structure

The following structure gives an expected layout for reference in examples below, as well as indicating how BUILD files and targets are used.

- repositoryRoot
  - area-A/
    - package.json with 'workspaces' defined (yarn, npm)
      - workspaces: ["packages/package-a", "packages/package-b", "packages/sub-dir/package-c"]
    - \[pnpm-workspace.yaml\] - pnpm only - will cause issues if present for npm/yarn
    - package-lock.json (or pnpm-lock.yaml or yarn.lock) - this is a generated file
    - BUILD
      - package_json()
    - packages/
      - package-a/
        - package.json
        - index.js
        - BUILD
          - package_json()
          - javascript_sources()
      - package-b/
        - package.json
        - index.js
        - BUILD
      - sub-dir/
        - package-c/
          - package.json
          - index.js
          - BUILD
  - area-B/
    - ...

## Backend functionality

NB: This is not exhaustive!

### Resolves

The resolve (lock file) is generated for each package.json location that is a root for workspaces.

Root package.jsons may not have overlapping workspaces - i.e a package may not be a member of multiple root package.jsons.


### Build and test scripts

Javascript packages may have build and test scripts defined in package.json. E.g. 

```json
{
  "main": "src/index.js",
  "name": "demo",
  "version": "0.0.1",
  "scripts": {
    "build": "esbuild --bundle --platform=node --target=node12 --outdir=./dist_npm src/index.js",
    "test": "jest"
  },
  "devDependencies": {
    "esbuild": "^0.20.1",
    "jest": "^29.7.0"
  }
}
```

Pants can run these with the `package` and `test` goals respectively. They must be added to the BUILD file as e.g. 

```python
package_json(
    name="demo_pkg",
    scripts=[
        node_build_script(
            entry_point="build", # this is the default value - corresponds to package.json["scripts"]["build"]
            extra_env_vars=["FOO=BAR"],
            output_files=["dist_npm/index.js"],
        ),      
        node_test_script(
            coverage_args=["--coverage", "--coverage-directory=.coverage/"],
            coverage_output_files=[".coverage/lcov-report/index.html"],
            coverage_output_directories=[".coverage/lcov-report"],
        ),
    ],
)
```

### Dependencies between packages

In the example above, for an installation of 'package-a' to also install 'package-c', the following things must in place:
- Both packages must be in a workspace - i.e. the directories added to a common parent package.json
- Import statement: package-a source code must contain an import statement like `const pc = require("package-c");` 
- Package.json dependency: e.g. `  "dependencies": {"package-b": "*" }` 

Import, package.json deps (correct/complete case)
- node_modules in workspace package.json directory contains:
  - directory for the package itself and its source code
  - directory for 1st party deps - e.g. 
  - directories for 3rd party deps, and transitive deps (3rd and/or 1st party)

No import, no package.json dep:
- node_modules contains package-a package.json, source code, and 3rd party dependencies

No import, package.json dep:
- node_modules missing source code for 1st party deps, everything else present
- Probably in this case, it would be nice to generate a warning, e.g. "Package-a source code has a dependency on package-b but package-b is not present in package-a's listed dependencies in package.json".

Import, no package.json dep:
- node_modules missing 1st party deps

Dependencies specified, but not package not in workspace:
- Package manager will try to install matching package from registry instead. (The pnpm workspaces protocol can be used to avoid this.
https://pnpm.io/workspaces#workspace-protocol-workspace)
- Note if a package is removed from the workspace and lockfile is not subsequently updated, the following error is triggered - "npm ERR! Cannot set properties of null (setting 'dev')"  

### Caches

Package manager caches are preserved (npm config cache, pnpm home, yarn cache). 
Extra caches can be provided for build and test scripts (e.g see `NodeBuildScriptExtraCaches`)

### Caching behavior on install

If the source code for package-a is modified, the package is not reinstalled - only the build script is re-run.

If any of the package.json files in the workspace is modified, this causes a reinstall, as the process for 'Preparing configured default npm version.', (and also the subsequent installation process) has these files as an input. 

It may be possible to limit this by only including the package.json files for packages' dependencies.
