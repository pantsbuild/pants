# Go Backend - Under Development!

Note: This Go backend is incomplete because it is under active development! Thus, it
definitely won't work yet for any real Go projects.

## Layout

- `src/python/pants/backend/go`: Backend
- `src/python/pants/backend/experimental/go`: Registration code
- `testprojects/src/go/pants_test`: Sample project

## Build sample project

```shell
$ ./pants \
  --backend-packages='pants.backend.experimental.go' \
  --build-ignore='-["/testprojects/src/go/**"]' \
  package \
  testprojects/src/go/pants_test::
$  ./dist/testprojects.src.go.pants_test/bin foo bar
arg[0] = >> ./dist/testprojects.src.go.pants_test/bin <<
arg[1] = >> foo <<
arg[2] = >> bar <<
```
