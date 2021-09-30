/* Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"strings"
)


//
// Parse Go sources and extract various metadata about the tests contained therein.
// Based in part on:
//   * rules_go (https://github.com/bazelbuild/rules_go/blob/master/go/tools/builders/generate_test_main.go)
//   * `go` tool (https://github.com/golang/go/blob/master/src/cmd/go/internal/load/test.go)
//
// As explained by the rules_go source:
//
// A Go test comprises three packages:
//
// 1. An internal test package, compiled from the sources of the library being
//    tested and any _test.go files with the same package name.
// 2. An external test package, compiled from _test.go files with a package
//    name ending with "_test".
// 3. A generated main package that imports both packages and initializes the
//    test framework with a list of tests, benchmarks, examples, and fuzz
//    targets read from source files.
//

type TestCase struct {
	Package string `json:"package"`
	Name string `json:"name"`
}

// TestSourcesMetadata contains metadata about tests/benchmarks extracted from the parsed sources.
// TODO: "Examples" and "fuzz targets" (Go 1.18+).
type TestSourcesMetadata struct {
	// Names of all functions in the test sources that heuristically look like test functions.
	Tests []*TestCase `json:"tests,omit_empty"`

	// Names of all functions in the test sources that heuristically look like benchmark functions.
	Benchmarks []*TestCase `json:"benchmarks,omit_empty"`

	// True if the sources already contain a `TestMain` function (which is the entry point for test binaries).
	HasTestMain bool `json:"has_test_main"`
}

func processFile(fileSet *token.FileSet, filename string) (*TestSourcesMetadata, error) {
	p, err := parser.ParseFile(fileSet, filename, nil, parser.ParseComments)
	if err != nil {
		return nil, fmt.Errorf("failed to parse: %s", err)
	}

	var metadata TestSourcesMetadata

	pkgName := p.Name.Name

	for _, decl := range p.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok {
			continue
		}
		if fn.Recv != nil {
			continue
		}

		// If the source has a `TestMain` function, then record that fact so that Pants knows to use the
		// user-supplied `TestMain` instead of generating a `TestMain`.
		if fn.Name.Name == "TestMain" {
			metadata.HasTestMain = true
			continue
		}

		// The following test/benchmark heuristic is based on the code in Bazel's rules_go.
		// https://github.com/bazelbuild/rules_go/blob/master/go/tools/builders/generate_test_main.go#L308-L367

		// Here we check the signature of the Test* function. To be considered a test:

		// 1. The function should have a single argument.
		if len(fn.Type.Params.List) != 1 {
			continue
		}

		// 2. The function should return nothing.
		if fn.Type.Results != nil {
			continue
		}

		// 3. The only parameter should have a type identified as
		//    *<something>.T
		starExpr, ok := fn.Type.Params.List[0].Type.(*ast.StarExpr)
		if !ok {
			continue
		}
		selExpr, ok := starExpr.X.(*ast.SelectorExpr)
		if !ok {
			continue
		}

		// We do not discriminate on the referenced type of the
		// parameter being *testing.T. Instead, we assert that it
		// should be *<something>.T. This is because the import
		// could have been aliased as a different identifier.

		if strings.HasPrefix(fn.Name.Name, "Test") {
			if selExpr.Sel.Name != "T" {
				continue
			}
			metadata.Tests = append(metadata.Tests, &TestCase{
				Name: fn.Name.Name,
				Package: pkgName,
			})
		}
		if strings.HasPrefix(fn.Name.Name, "Benchmark") {
			if selExpr.Sel.Name != "B" {
				continue
			}
			metadata.Benchmarks = append(metadata.Benchmarks, &TestCase{
				Name: fn.Name.Name,
				Package: pkgName,
			})
		}
	}

	return &metadata, nil
}

func main() {
	var allMetadata TestSourcesMetadata

	fileSet := token.NewFileSet()
	for _, arg := range os.Args[1:] {
		fileMetadata, err := processFile(fileSet, arg)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: %s", arg, err)
			os.Exit(1)
		}

		// TODO: Flag duplicate test and benchmark names.
		allMetadata.Tests = append(allMetadata.Tests, fileMetadata.Tests...)
		allMetadata.Benchmarks = append(allMetadata.Benchmarks, fileMetadata.Benchmarks...)

		// TODO: Ensure only one TestMain function and flag duplicates.
		allMetadata.HasTestMain = allMetadata.HasTestMain || fileMetadata.HasTestMain
	}

	output, err := json.Marshal(&allMetadata)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Unable to marshall JSON output: %s", err)
		os.Exit(1)
	}

	output = append(output, []byte{'\n'}...)

	amtWritten := 0
	for amtWritten < len(output) {
		n, err := os.Stdout.Write(output[amtWritten:])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to write output: %s", err)
			os.Exit(1)
		}
		amtWritten += n
	}



	os.Exit(0)
}