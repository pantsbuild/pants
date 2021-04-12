# GoLang Backend - Under Development!

Note: This Go backend is incomplete because it is under active development! Thus, it
definitely won't work yet for any real Go projects.

## Overview

Currently only supports:

- Run gofmt on Go sources via `fmt` goal (`lint` goal works as well)
- Build Go binaries from first-party code (but does handle first-party dependencies) via `package` goal
- Compile Go sources via `go-build` custom goal.

Areas for development:

- Go modules support / third-party dependencies
- Dependency inference
- Tests
  * Build and run test binaries
- Use `go list` to extract modules in standard library.
- Code generation

## Layout

- `src/python/pants/backend/experimental/golang`: Backend
- `testprojects/src/go/pants_test`: Sample project

## Build sample project

```shell
$ ./pants \
  --backend-packages='pants.backend.experimental.golang' \
  --build-ignore='-["/testprojects/src/go/**"]' \
  package \
  testprojects/src/go/pants_test::
$  ./dist/testprojects.src.go.pants_test/bin foo bar
arg[0] = >> ./dist/testprojects.src.go.pants_test/bin <<
arg[1] = >> foo <<
arg[2] = >> bar <<
```
