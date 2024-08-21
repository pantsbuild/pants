# TypeScript Backend - Under Development!

The TypeScript backend is incomplete because it is under active development! Thus, it
may not be used for any real TypeScript projects in production.

## Functionality

After enabling the `"pants.backend.experimental.typescript"` backend in the `pants.toml` file, you can:

* run `pants tailor ::` to create `typescript_sources()` and `typescript_tests` target generators

## Dependency inference

The dependencies are not yet fully discovered during dependency inference and support for all the import
syntax variations is being added. See https://www.typescriptlang.org/docs/handbook/2/modules.html to learn more.

Currently supported:

* file-based imports

```typescript
// in src/ts/index.ts
import { x } from "./localModuleA";
import { y } from "./localModuleB";
```

would be discovered as

```
$ pants dependencies src/ts/index.ts
src/ts/localModuleA.ts
src/ts/localModuleB.ts
```
