---
title: "Protobuf"
slug: "protobuf-go"
excerpt: "How to generate Go from Protocol Buffers."
hidden: false
createdAt: "2022-04-20T22:34:22.819Z"
updatedAt: "2022-04-25T23:26:26.127Z"
---
When your Go code imports Protobuf generated files, Pants will detect the imports and run the Protoc compiler to generate then compile those files.
[block:callout]
{
  "type": "info",
  "title": "Example repository",
  "body": "See [the codegen example repository](https://github.com/pantsbuild/example-codegen) for an example of using Protobuf to generate Go."
}
[/block]

[block:callout]
{
  "type": "success",
  "body": "With Pants, there's no need to manually regenerate your code or check it into version control. Pants will ensure you are always using up-to-date files in your builds.\n\nThanks to fine-grained caching, Pants will regenerate the minimum amount of code required when you do make changes.",
  "title": "Benefit of Pants: generated files are always up-to-date"
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "`go mod tidy` will complain about missing modules",
  "body": "Because Pants does not save generated code to disk, `go mod tidy` will error that it cannot find the generated packages.\n\nOne workaround is to run `./pants export-codegen ::` to save the generated files."
}
[/block]

[block:api-header]
{
  "title": "Step 1: Activate the Protobuf Go backend"
}
[/block]
Add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  \"pants.backend.experimental.codegen.protobuf.go\",\n  \"pants.backend.experimental.go\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
This adds the new [`protobuf_source`](doc:reference-protobuf_source) target, which you can confirm by running `./pants help protobuf_source`. 

To reduce boilerplate, you can also use the [`protobuf_sources`](doc:reference-protobuf_sources) target, which generates one `protobuf_source` target per file in the `sources` field.
[block:code]
{
  "codes": [
    {
      "code": "protobuf_sources(name=\"protos\", sources=[\"user.proto\", \"admin.proto\"])\n\n# Spiritually equivalent to:\nprotobuf_source(name=\"user\", source=\"user.proto\")\nprotobuf_source(name=\"admin\", source=\"admin.proto\")\n\n# Thanks to the default `sources` value of '*.proto', spiritually equivalent to:\nprotobuf_sources(name=\"protos\")",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Step 2: Set up your `go.mod` and `go.sum`"
}
[/block]
The generated Go code requires `google.golang.org/protobuf` to compile. Add it to your `go.mod` with the version you'd like. Then run `go mod download all` to update your `go.sum`.
[block:code]
{
  "codes": [
    {
      "code": "require google.golang.org/protobuf v1.27.1",
      "language": "text",
      "name": "go.mod"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Step 3: Add `option go_package` to `.proto` files"
}
[/block]
Every Protobuf file that should work with Go must set `option go_package` with the name of its Go package. For example:
[block:code]
{
  "codes": [
    {
      "code": "syntax = \"proto3\";\n\npackage simple_example.v1;\n\noption go_package = \"github.com/pantsbuild/example-codegen/gen\";",
      "language": "text",
      "name": "src/protos/example/v1/person.proto"
    }
  ]
}
[/block]
Multiple Protobuf files can set the same `go_package` if their code should show up in the same package.
[block:api-header]
{
  "title": "Step 4: Generate `protobuf_sources` targets"
}
[/block]
Run [`./pants tailor ::`](doc:create-initial-build-files) for Pants to create a `protobuf_sources` target wherever you have `.proto` files:

```
❯ ./pants tailor ::
Created src/protos/BUILD:
  - Add protobuf_sources target protos
```

Pants will use [dependency inference](doc:targets) for any `import` statements in your `.proto` files, which you can confirm by running `./pants dependencies path/to/file.proto`.

If you want gRPC code generated for all files in the folder, set `grpc=True`.
[block:code]
{
  "codes": [
    {
      "code": "protobuf_sources(\n    name=\"protos\",\n    grpc=True,\n)",
      "language": "python",
      "name": "src/proto/example/BUILD"
    }
  ]
}
[/block]
If you only want gRPC generated for some files in the folder, you can use the `overrides` field:
[block:code]
{
  "codes": [
    {
      "code": "protobuf_sources(\n    name=\"protos\",\n    overrides={\n        \"admin.proto\": {\"grpc\": True},\n        # You can also use a tuple for multiple files.\n        (\"user.proto\", \"org.proto\"): {\"grpc\": True},\n    },\n)",
      "language": "python",
      "name": "src/proto/example/BUILD"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Step 5: Confirm Go imports are working"
}
[/block]
Now, you can import the generated Go package in your Go code like normal, using whatever you set with `option go_package` from Step 3.
[block:code]
{
  "codes": [
    {
      "code": "package examples\n\nimport \"testing\"\nimport \"github.com/pantsbuild/example-codegen/gen\"\n\nfunc TestGenerateUuid(t *testing.T) {\n\tperson := gen.Person{\n\t\tName:  \"Thomas the Train\",\n\t\tId:    1,\n\t\tEmail: \"allaboard@trains.build\",\n\t}\n\tif person.Name != \"Thomas the Train\" {\n\t\tt.Fail()\n\t}\n}\n",
      "language": "go",
      "name": "src/go/examples/proto_test.go"
    }
  ]
}
[/block]
Pants's dependency inference will detect Go imports of Protobuf packages, which you can confirm by running `./pants dependencies path/to/file.go`. You can also run `./pants check path/to/file.go` to confirm that everything compiles.
[block:callout]
{
  "type": "info",
  "title": "Run `./pants export-codegen ::` to inspect the files",
  "body": "`./pants export-codegen ::` will run all relevant code generators and write the files to `dist/codegen` using the same paths used normally by Pants.\n\nYou do not need to run this goal for codegen to work when using Pants; `export-codegen` is only for external consumption outside of Pants, e.g. to get `go mod tidy` working."
}
[/block]

[block:api-header]
{
  "title": "Buf: format and lint Protobuf"
}
[/block]
Pants integrates with the [`Buf`](https://buf.build/blog/introducing-buf-format) formatter and linter for Protobuf files.

To activate, add this to `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  \"pants.backend.codegen.protobuf.lint.buf\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]

Now you can run `./pants fmt` and `./pants lint`:

```
❯ ./pants lint src/protos/user.proto
```

Use `./pants fmt lint dir:` to run on all files in the directory, and `./pants fmt lint dir::` to run on all files in the directory and subdirectories.

Temporarily disable Buf with `--buf-fmt-skip` and `--buf-lint-skip`:

```bash
❯ ./pants --buf-fmt-skip fmt ::
```

Only run Buf with `--lint-only=buf-fmt` or `--lint-only=buf-lint`, and `--fmt-only=buf-fmt`:

```bash
❯ ./pants fmt --only=buf-fmt ::
```