/* Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 *
 * Parts adapted from Go SDK and Bazel rules_go, both under BSD-compatible licenses.
 */

package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"go/ast"
	"go/build"
	"go/doc"
	"go/parser"
	"go/token"
	"os"
	"strings"
	"text/template"
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

// Analysis contains metadata about tests/benchmarks extracted from the parsed sources.
type Analysis struct {
	// Names of all functions in the test sources that heuristically look like test functions.
	Tests []*TestFunc

	// Names of all functions in the test sources that heuristically look like benchmark functions.
	Benchmarks []*TestFunc

	// Testable examples. Extracted using "go/doc" package.
	Examples []*Example

	// Fuzz targets (supported on Go 1.18+).
	FuzzTargets []*TestFunc

	// Set with location of any `TestMain` function. `nil` if no `TestMain` supplied.
	TestMain *TestFunc

	ImportPath  string
	ImportTest  bool
	ImportXTest bool
	NeedTest    bool
	NeedXTest   bool

	// True if Go 1.18 is in use. This is not set by analyze but rather by generate based on release tags.
	IsGo1_18 bool

	// True if coverage is enabled. This is not set by `analyze` but rather by `generate` based on an
	// environment variable set by the invoker.
	Cover bool
}

// isTestFunc tells whether fn has the type of a testing function. arg
// specifies the parameter type we look for: B, M, T or F.
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

func processFile(fileSet *token.FileSet, pkgName string, filename string) (*Analysis, error) {
	p, err := parser.ParseFile(fileSet, filename, nil, parser.ParseComments)
	if err != nil {
		return nil, fmt.Errorf("failed to parse: %s", err)
	}

	var analysis Analysis

	for _, e := range doc.Examples(p) {
		if e.Output == "" && !e.EmptyOutput {
			// Don't run examples with no output directive.
			continue
		}
		analysis.Examples = append(analysis.Examples, &Example{
			Name:      "Example" + e.Name,
			Package:   pkgName,
			Output:    e.Output,
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
				analysis.Tests = append(analysis.Tests, &TestFunc{
					Name:    fn.Name.Name,
					Package: pkgName,
				})
				continue
			}
			err := checkTestFunc(fileSet, fn, "M")
			if err != nil {
				return nil, err
			}
			if analysis.TestMain != nil {
				return nil, errors.New("multiple definitions of TestMain")
			}
			analysis.TestMain = &TestFunc{
				Name:    fn.Name.Name,
				Package: pkgName,
			}
		case isTest(name, "Test"):
			err := checkTestFunc(fileSet, fn, "T")
			if err != nil {
				return nil, err
			}
			analysis.Tests = append(analysis.Tests, &TestFunc{
				Name:    fn.Name.Name,
				Package: pkgName,
			})
		case isTest(name, "Benchmark"):
			err := checkTestFunc(fileSet, fn, "B")
			if err != nil {
				return nil, err
			}
			analysis.Benchmarks = append(analysis.Benchmarks, &TestFunc{
				Name:    fn.Name.Name,
				Package: pkgName,
			})
		case isTest(name, "Fuzz"):
			err := checkTestFunc(fileSet, fn, "F")
			if err != nil {
				return nil, err
			}
			analysis.FuzzTargets = append(analysis.FuzzTargets, &TestFunc{
				Name:    fn.Name.Name,
				Package: pkgName,
			})
		}
	}

	if len(analysis.Tests) > 0 ||
		len(analysis.Benchmarks) > 0 ||
		len(analysis.Examples) > 0 ||
		len(analysis.FuzzTargets) > 0 ||
		analysis.TestMain != nil {
		switch pkgName {
		case "_test":
			analysis.NeedTest = true
		case "_xtest":
			analysis.NeedXTest = true
		default:
			panic("Unknown package name")
		}
	}

	return &analysis, nil
}

func analyze(importPath string, files []string) (*Analysis, error) {
	analysis := Analysis{
		ImportPath: importPath,
	}

	fileSet := token.NewFileSet()
	for _, arg := range files {
		parts := strings.SplitN(arg, ":", 2)
		switch parts[0] {
		case "_test":
			analysis.ImportTest = true
		case "_xtest":
			analysis.ImportXTest = true
		default:
			panic("Unknown package name")
		}

		fileMetadata, err := processFile(fileSet, parts[0], parts[1])
		if err != nil {
			return nil, fmt.Errorf("%s: %s", parts[1], err)
		}

		// TODO: Flag duplicate test and benchmark names.
		analysis.Tests = append(analysis.Tests, fileMetadata.Tests...)
		analysis.Benchmarks = append(analysis.Benchmarks, fileMetadata.Benchmarks...)
		analysis.FuzzTargets = append(analysis.FuzzTargets, fileMetadata.FuzzTargets...)
		analysis.Examples = append(analysis.Examples, fileMetadata.Examples...)
		if fileMetadata.TestMain != nil {
			if analysis.TestMain != nil {
				return nil, errors.New("multiple definitions of TestMain")
			}
			analysis.TestMain = fileMetadata.TestMain
		}
		analysis.NeedTest = analysis.NeedTest || fileMetadata.NeedTest
		analysis.NeedXTest = analysis.NeedXTest || fileMetadata.NeedXTest
	}

	return &analysis, nil
}

var testMainTemplate = `
// Code generated by Pants for test binary. DO NOT EDIT.
package main
import (
	"os"
{{- if .TestMain}}
	"reflect"
{{- end}}
	"testing"
	"testing/internal/testdeps"
{{- if .ImportTest}}
	{{if .NeedTest}}_test{{else}}_{{end}} {{.ImportPath | printf "%q"}}
{{- end}}
{{- if .ImportXTest}}
	{{if .NeedXTest}}_xtest{{else}}_{{end}} {{.ImportPath | printf "%s_test" | printf "%q"}}
{{- end}}
)

var tests = []testing.InternalTest{
{{- range .Tests}}
	{"{{.Name}}", {{.Package}}.{{.Name}}},
{{- end}}
}

var benchmarks = []testing.InternalBenchmark{
{{- range .Benchmarks}}
	{"{{.Name}}", {{.Package}}.{{.Name}}},
{{- end}}
}

var examples = []testing.InternalExample{
{{- range .Examples}}
	{"{{.Name}}", {{.Package}}.{{.Name}}, {{.Output | printf "%q"}}, {{.Unordered}}},
{{- end }}
}

{{ if .IsGo1_18 -}}
var fuzzTargets = []testing.InternalFuzzTarget{
{{- range .FuzzTargets }}
	{"{{.Name}}", {{.Package}}.{{.Name}}},
{{- end }}
}
{{- end }}

func init() {
	testdeps.ImportPath = "{{.ImportPath}}"
}

func main() {
{{if .Cover}}
	registerCover()
{{end}}

{{- if .IsGo1_18 }}
	m := testing.MainStart(testdeps.TestDeps{}, tests, benchmarks, fuzzTargets, examples)
{{- else }}
	m := testing.MainStart(testdeps.TestDeps{}, tests, benchmarks, examples)
{{- end}}
{{- with .TestMain }}
	{{.Package}}.{{.Name}}(m)
	os.Exit(int(reflect.ValueOf(m).Elem().FieldByName("exitCode").Int()))
{{- else }}
	os.Exit(m.Run())
{{- end }}
}
`

func generate(analysis *Analysis, genCover bool) ([]byte, error) {
	tmpl, err := template.New("testmain").Parse(testMainTemplate)
	if err != nil {
		return nil, err
	}

	// Detect Go 1.18+ (which all set the "go1.18" release tag) to account for the API change
	// made in the `testing` package to support fuzz targets.
	for _, tag := range build.Default.ReleaseTags {
		if tag == "go1.18" {
			analysis.IsGo1_18 = true
		}
	}

	// Pass through the config to generate the call to the coverage stubs.
	analysis.Cover = genCover

	var buffer bytes.Buffer

	err = tmpl.Execute(&buffer, analysis)
	if err != nil {
		return nil, err
	}

	return buffer.Bytes(), nil
}

func main() {
	analysis, err := analyze(os.Args[1], os.Args[2:])
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s\n", err)
		os.Exit(1)
	}

	genCover := os.Getenv("GENERATE_COVER") != ""

	testmain, err := generate(analysis, genCover)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to generate _testmain.go: %s\n", err)
		os.Exit(1)
	}

	err = os.WriteFile("_testmain.go", testmain, 0600)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to write _testmain.go: %s\n", err)
		os.Exit(1)
	}

	metadata := map[string]interface{}{
		"has_tests":  analysis.NeedTest,
		"has_xtests": analysis.NeedXTest,
	}

	metadataBytes, err := json.Marshal(&metadata)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to encode metadata: %s\n", err)
		os.Exit(1)
	}
	_, err = os.Stdout.Write(metadataBytes)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to write metadata: %s\n", err)
		os.Exit(1)
	}

	os.Exit(0)
}
