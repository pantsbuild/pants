/* Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 *
 * Parts adapted from Go SDK and Bazel rules_go, both under BSD-compatible licenses.
 */

package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"go/ast"
	"go/doc"
	"go/parser"
	"go/token"
	"os"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

//
// Parse Go sources and extract various metadata about the tests contained therein.
// Based in part on the `go` tool (https://github.com/golang/go/blob/master/src/cmd/go/internal/load/test.go)
// (under BSD-compatible license).
//
// As explained by the Bazel rules_go source:
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
// https://github.com/bazelbuild/rules_go/blob/master/go/tools/builders/generate_test_main.go
//

type TestFunc struct {
	Package string `json:"package"`
	Name    string `json:"name"`
}

type Example struct {
	Package   string `json:"package"`
	Name      string `json:"name"`
	Output    string `json:"output"`
	Unordered bool   `json:"unordered"`
}

// TestSourcesMetadata contains metadata about tests/benchmarks extracted from the parsed sources.
// TODO: "Examples" and "fuzz targets" (Go 1.18+).
type TestSourcesMetadata struct {
	// Names of all functions in the test sources that heuristically look like test functions.
	Tests []*TestFunc `json:"tests,omitempty"`

	// Names of all functions in the test sources that heuristically look like benchmark functions.
	Benchmarks []*TestFunc `json:"benchmarks,omitempty"`

	// Testable examples. Extracted using "go/doc" package.
	Examples []*Example `json:"examples,omitempty"`

	// True if the sources already contain a `TestMain` function (which is the entry point for test binaries).
	TestMain *TestFunc `json:"test_main,omitempty"`
}

// isTestFunc tells whether fn has the type of a testing function. arg
// specifies the parameter type we look for: B, M or T.
func isTestFunc(fn *ast.FuncDecl, arg string) bool {
	if (fn.Type.Results != nil && len(fn.Type.Results.List) > 0) ||
		fn.Type.Params.List == nil ||
		len(fn.Type.Params.List) != 1 ||
		len(fn.Type.Params.List[0].Names) > 1 {
		return false
	}
	ptr, ok := fn.Type.Params.List[0].Type.(*ast.StarExpr)
	if !ok {
		return false
	}
	// We can't easily check that the type is *testing.M
	// because we don't know how testing has been imported,
	// but at least check that it's *M or *something.M.
	// Same applies for B and T.
	if name, ok := ptr.X.(*ast.Ident); ok && name.Name == arg {
		return true
	}
	if sel, ok := ptr.X.(*ast.SelectorExpr); ok && sel.Sel.Name == arg {
		return true
	}
	return false
}

// isTest tells whether name looks like a test (or benchmark, according to prefix).
// It is a test if there is a character after Test that is not a lower-case letter.
// This avoids, for example, Testify matching.
func isTest(name, prefix string) bool {
	if !strings.HasPrefix(name, prefix) {
		return false
	}
	if len(name) == len(prefix) { // "Test" is ok
		return true
	}
	r, _ := utf8.DecodeRuneInString(name[len(prefix):])
	return !unicode.IsLower(r)
}

func checkTestFunc(fileSet *token.FileSet, fn *ast.FuncDecl, arg string) error {
	if !isTestFunc(fn, arg) {
		name := fn.Name.String()
		pos := fileSet.Position(fn.Pos())
		return fmt.Errorf("%s: wrong signature for %s, must be: func %s(%s *testing.%s)", pos, name, name, strings.ToLower(arg), arg)
	}
	return nil
}

func processFile(fileSet *token.FileSet, pkgName string, filename string) (*TestSourcesMetadata, error) {
	p, err := parser.ParseFile(fileSet, filename, nil, parser.ParseComments)
	if err != nil {
		return nil, fmt.Errorf("failed to parse: %s", err)
	}

	var metadata TestSourcesMetadata

	for _, e := range doc.Examples(p) {
		if e.Output == "" && !e.EmptyOutput {
			// Don't run examples with no output directive.
			continue
		}
		metadata.Examples = append(metadata.Examples, &Example{
			Name:      "Example" + e.Name,
			Package:   pkgName,
			Output:    strconv.Quote(e.Output),
			Unordered: e.Unordered,
		})
	}

	for _, decl := range p.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok {
			continue
		}
		if fn.Recv != nil {
			continue
		}

		// The following test/benchmark heuristic is based on the code in the `go` tool.
		// https://github.com/golang/go/blob/94323206aee1363471a4ae3b8d40dd4ae7a5cd9c/src/cmd/go/internal/load/test.go#L626-L665

		name := fn.Name.String()
		switch {
		case name == "TestMain":
			if isTestFunc(fn, "T") {
				// Handle a TestMain function that is actually a test and not a true TestMain.
				metadata.Tests = append(metadata.Tests, &TestFunc{
					Name:    fn.Name.Name,
					Package: pkgName,
				})
				continue
			}
			err := checkTestFunc(fileSet, fn, "M")
			if err != nil {
				return nil, err
			}
			if metadata.TestMain != nil {
				return nil, errors.New("multiple definitions of TestMain")
			}
			metadata.TestMain = &TestFunc{
				Name:    fn.Name.Name,
				Package: pkgName,
			}
		case isTest(name, "Test"):
			err := checkTestFunc(fileSet, fn, "T")
			if err != nil {
				return nil, err
			}
			metadata.Tests = append(metadata.Tests, &TestFunc{
				Name:    fn.Name.Name,
				Package: pkgName,
			})
		case isTest(name, "Benchmark"):
			err := checkTestFunc(fileSet, fn, "B")
			if err != nil {
				return nil, err
			}
			metadata.Benchmarks = append(metadata.Benchmarks, &TestFunc{
				Name:    fn.Name.Name,
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
		parts := strings.SplitN(arg, ":", 2)

		fileMetadata, err := processFile(fileSet, parts[0], parts[1])
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: %s\n", parts[1], err)
			os.Exit(1)
		}

		// TODO: Flag duplicate test and benchmark names.
		allMetadata.Tests = append(allMetadata.Tests, fileMetadata.Tests...)
		allMetadata.Benchmarks = append(allMetadata.Benchmarks, fileMetadata.Benchmarks...)
		allMetadata.Examples = append(allMetadata.Examples, fileMetadata.Examples...)
		if fileMetadata.TestMain != nil {
			if allMetadata.TestMain != nil {
				fmt.Fprintf(os.Stderr, "multiple definitions of TestMain\n")
				os.Exit(1)
			}
			allMetadata.TestMain = fileMetadata.TestMain
		}
	}

	output, err := json.Marshal(&allMetadata)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Unable to marshall JSON output: %s\n", err)
		os.Exit(1)
	}

	output = append(output, []byte{'\n'}...)

	amtWritten := 0
	for amtWritten < len(output) {
		n, err := os.Stdout.Write(output[amtWritten:])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Failed to write output: %s\n", err)
			os.Exit(1)
		}
		amtWritten += n
	}

	os.Exit(0)
}
