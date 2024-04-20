# Javascript Backend

This README is mainly for the purposes of understanding the current backend functionality for PR review purposes, 
plan to migrate most of this to user docs once that is ready. 

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

## Repo Structure

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

## Expected behavior

### Resolves

The resolve (lock file) is generated for each package.json location that is a root for workspaces.

Root package.json's may not have overlapping workspaces - i.e a package may not be a member of multiple root package.jsons.


## Dependencies

Dependencies are inferred from javascript source code. 

In the example above, for an installation of 'package-a' to also install 'package-c'

No import, no package.json deps: 
- node_modules contains package-a, package-a source and package-a 3rd party dependencies

No import, package.json deps
- node_modules - as above - plus package-b 3rd party deps, but no source for package-b

Import, no package.json deps
- packages/ directory contains source code for first party dependencies
- node_modules does not contain first party dependencies

Import, package.json deps
- node_modules - all packages with source


In all scenarios, packages/<dir name> contains the package.json files - this is necessary for package resolution at workspaces level.
...

Dependencies specified, but not in workspaces
- It will try to install matching package from registry instead. The pnpm workspaces protocol can be used to avoid this.
https://pnpm.io/workspaces#workspace-protocol-workspace
- If workspace item removed without first updating lockfile - "npm ERR! Cannot set properties of null (setting 'dev')"  



## Caching

If the source code for package-a is modified, the package is not reinstalled - only the build script is re-run.
