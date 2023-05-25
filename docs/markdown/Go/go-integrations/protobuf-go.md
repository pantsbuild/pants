---
title: "Protobuf"
slug: "protobuf-go"
excerpt: "How to generate Go from Protocol Buffers."
hidden: false
createdAt: "2022-04-20T22:34:22.819Z"
---
When your Go code imports Protobuf generated files, Pants will detect the imports and run the Protoc compiler to generate then compile those files.

> 📘 Example repository
> 
> See [the codegen example repository](https://github.com/pantsbuild/example-codegen) for an example of using Protobuf to generate Go.

> 👍 Benefit of Pants: generated files are always up-to-date
> 
> With Pants, there's no need to manually regenerate your code or check it into version control. Pants will ensure you are always using up-to-date files in your builds.
> 
> Thanks to fine-grained caching, Pants will regenerate the minimum amount of code required when you do make changes.

> 🚧 `go mod tidy` will complain about missing modules
> 
> Because Pants does not save generated code to disk, `go mod tidy` will error that it cannot find the generated packages.
> 
> One workaround is to run `pants export-codegen ::` to save the generated files.

Step 1: Activate the Protobuf Go backend
----------------------------------------

Add this to your `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages = [
  "pants.backend.experimental.codegen.protobuf.go",
  "pants.backend.experimental.go",
]
```

This adds the new [`protobuf_source`](doc:reference-protobuf_source) target, which you can confirm by running `pants help protobuf_source`. 

To reduce boilerplate, you can also use the [`protobuf_sources`](doc:reference-protobuf_sources) target, which generates one `protobuf_source` target per file in the `sources` field.

```python BUILD
protobuf_sources(name="protos", sources=["user.proto", "admin.proto"])

# Spiritually equivalent to:
protobuf_source(name="user", source="user.proto")
protobuf_source(name="admin", source="admin.proto")

# Thanks to the default `sources` value of '*.proto', spiritually equivalent to:
protobuf_sources(name="protos")
```

Step 2: Set up your `go.mod` and `go.sum`
-----------------------------------------

The generated Go code requires `google.golang.org/protobuf` to compile. Add it to your `go.mod` with the version you'd like. Then run `go mod download all` to update your `go.sum`.

```text go.mod
require google.golang.org/protobuf v1.27.1
```

Step 3: Add `option go_package` to `.proto` files
-------------------------------------------------

Every Protobuf file that should work with Go must set `option go_package` with the name of its Go package. For example:

```text src/protos/example/v1/person.proto
syntax = "proto3";

package simple_example.v1;

option go_package = "github.com/pantsbuild/example-codegen/gen";
```

Multiple Protobuf files can set the same `go_package` if their code should show up in the same package.

Step 4: Generate `protobuf_sources` targets
-------------------------------------------

Run [`pants tailor ::`](doc:initial-configuration#5-generate-build-files) for Pants to create a `protobuf_sources` target wherever you have `.proto` files:

```
❯ pants tailor ::
Created src/protos/BUILD:
  - Add protobuf_sources target protos
```

Pants will use [dependency inference](doc:targets) for any `import` statements in your `.proto` files, which you can confirm by running `pants dependencies path/to/file.proto`.

If you want gRPC code generated for all files in the folder, set `grpc=True`.

```python src/proto/example/BUILD
protobuf_sources(
    name="protos",
    grpc=True,
)
```

If you only want gRPC generated for some files in the folder, you can use the `overrides` field:

```python src/proto/example/BUILD
protobuf_sources(
    name="protos",
    overrides={
        "admin.proto": {"grpc": True},
        # You can also use a tuple for multiple files.
        ("user.proto", "org.proto"): {"grpc": True},
    },
)
```

Step 5: Confirm Go imports are working
--------------------------------------

Now, you can import the generated Go package in your Go code like normal, using whatever you set with `option go_package` from Step 3.

```go src/go/examples/proto_test.go
package examples

import "testing"
import "github.com/pantsbuild/example-codegen/gen"

func TestGenerateUuid(t *testing.T) {
	person := gen.Person{
		Name:  "Thomas the Train",
		Id:    1,
		Email: "allaboard@trains.build",
	}
	if person.Name != "Thomas the Train" {
		t.Fail()
	}
}
```

Pants's dependency inference will detect Go imports of Protobuf packages, which you can confirm by running `pants dependencies path/to/file.go`. You can also run `pants check path/to/file.go` to confirm that everything compiles.

> 📘 Run `pants export-codegen ::` to inspect the files
> 
> `pants export-codegen ::` will run all relevant code generators and write the files to `dist/codegen` using the same paths used normally by Pants.
> 
> You do not need to run this goal for codegen to work when using Pants; `export-codegen` is only for external consumption outside of Pants, e.g. to get `go mod tidy` working.

Buf: format and lint Protobuf
-----------------------------

Pants integrates with the [`Buf`](https://buf.build/blog/introducing-buf-format) formatter and linter for Protobuf files.

To activate, add this to `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages = [
  "pants.backend.codegen.protobuf.lint.buf",
]
```

Now you can run `pants fmt` and `pants lint`:

```
❯ pants lint src/protos/user.proto
```

Use `pants fmt lint dir:` to run on all files in the directory, and `pants fmt lint dir::` to run on all files in the directory and subdirectories.

Temporarily disable Buf with `--buf-fmt-skip` and `--buf-lint-skip`:

```bash
❯ pants --buf-fmt-skip fmt ::
```

Only run Buf with `--lint-only=buf-fmt` or `--lint-only=buf-lint`, and `--fmt-only=buf-fmt`:

```bash
❯ pants fmt --only=buf-fmt ::
```
