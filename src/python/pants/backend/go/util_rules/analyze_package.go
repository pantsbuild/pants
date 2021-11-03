/* Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

/*
 * Analyze a Go package for imports and other metadata.
 *
 * Note: `go list` can return this data but requires the full set of dependencies to be available. It is much
 * better for performance to not copy those dependencies into the input root. Hence doing this analysis here.
 *
 * Loosely based on the analysis in the go/build stdlib module.
 * See https://cs.opensource.google/go/go/+/refs/tags/go1.17.2:src/go/build/build.go;drc=refs%2Ftags%2Fgo1.17.2;l=512.
 */

package main

import (
	"encoding/json"
	"fmt"
	"go/build"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type Package struct {
	Name string `json:"name"`

	Imports      []string `json:"imports,omitempty"`
	TestImports  []string `json:"test_imports,omitempty"`
	XTestImports []string `json:"xtest_imports,omitempty"`

	GoFiles []string `json:"go_files,omitempty"`
	SFiles  []string `json:"s_files,omitempty"`

	InvalidGoFiles    map[string]string `json:"invalid_go_files,omitempty"`
	IgnoredGoFiles    []string          `json:"ignored_go_files,omitempty"'`
	IgnoredOtherFiles []string          `json:"ignored_other_files,omitempty"`

	TestGoFiles  []string `json:"test_go_files,omitempty"`
	XTestGoFiles []string `json:"xtest_go_files,omitempty"`
}

type fileAnalysis struct {
	Name    string
	Imports []string
}

func analyzeFile(fileSet *token.FileSet, filename string) (*fileAnalysis, error) {
	parsed, err := parser.ParseFile(fileSet, filename, nil, parser.ImportsOnly|parser.ParseComments)
	if err != nil {
		return nil, err
	}

	analysis := &fileAnalysis{}

	analysis.Name = parsed.Name.Name
	for _, spec := range parsed.Imports {
		importPath, err := strconv.Unquote(spec.Path.Value)
		if err != nil {
			return nil, fmt.Errorf("unable to decode import: %s", spec.Path.Value)
		}
		analysis.Imports = append(analysis.Imports, importPath)
	}

	return analysis, nil
}

// Vendored from https://cs.opensource.google/go/go/+/refs/tags/go1.17.2:src/go/build/build.go;l=1024;drc=refs%2Ftags%2Fgo1.17.2
func fileListForExt(p *Package, ext string) *[]string {
	switch ext {
	//case ".c":
	//	return &p.CFiles
	//case ".cc", ".cpp", ".cxx":
	//	return &p.CXXFiles
	//case ".m":
	//	return &p.MFiles
	//case ".h", ".hh", ".hpp", ".hxx":
	//	return &p.HFiles
	//case ".f", ".F", ".for", ".f90":
	//	return &p.FFiles
	case ".s", ".S", ".sx":
		return &p.SFiles
		//case ".swig":
		//	return &p.SwigFiles
		//case ".swigcxx":
		//	return &p.SwigCXXFiles
		//case ".syso":
		//	return &p.SysoFiles
	}
	return nil
}

func analyzePackage(directory string, buildContext *build.Context) (*Package, error) {
	fileSet := token.NewFileSet()

	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, fmt.Errorf("failed to read directory %s: %s", directory, err)
	}

	// Keep track of the names used in `package` directives to ensure that only one package name is used.
	packageNames := make(map[string]bool)

	pkg := &Package{
		InvalidGoFiles: make(map[string]string),
	}

	importsMap := make(map[string]bool)
	testImportsMap := make(map[string]bool)
	xtestImportsMap := make(map[string]bool)

	for _, entry := range entries {
		if entry.IsDir() {
			// TODO: Consider flagging existence of a testdata directory.
			continue
		}

		name := entry.Name()
		ext := filepath.Ext(name)

		// TODO: `MatchFile` will actually parse the imports but does not return the AST. Consider vendoring
		// the MatchFile logic to avoid double parsing.
		matches, err := buildContext.MatchFile(directory, name)
		if err != nil {
			return nil, fmt.Errorf("failed to check build tags for %s: %s", name, err)
		}
		if !matches {
			if strings.HasPrefix(name, "_") || strings.HasPrefix(name, ".") {
				// `go` ignores files prefixed with underscore or period. Since this is not due to
				// build constraints, do not report it as an ignored file. Fall through.
			} else if ext == ".go" {
				pkg.IgnoredGoFiles = append(pkg.IgnoredGoFiles, name)
			} else if fileListForExt(pkg, ext) != nil {
				pkg.IgnoredOtherFiles = append(pkg.IgnoredOtherFiles, name)
			}
			continue
		}

		// Going to save the file. For non-Go files, can stop here.
		switch ext {
		case ".go":
			// keep going
		case ".S", ".sx":
			// special case for cgo, handled at end
			//Sfiles = append(Sfiles, name)
			continue
		default:
			if list := fileListForExt(pkg, ext); list != nil {
				*list = append(*list, name)
			}
			continue
		}

		analysis, err := analyzeFile(fileSet, filepath.Join(directory, name))
		if err != nil {
			pkg.InvalidGoFiles[name] = err.Error()
			// Fall-through to allow listing the file's existence.
		}

		var pkgName string
		if analysis != nil {
			pkgName = analysis.Name
			if pkgName == "documentation" {
				pkg.IgnoredGoFiles = append(pkg.IgnoredGoFiles, name)
				continue
			}
		}

		isTest := strings.HasSuffix(name, "_test.go")
		isXTest := false
		if isTest && strings.HasSuffix(analysis.Name, "_test") {
			isXTest = true
			pkgName = pkgName[:len(pkgName)-len("_test")]
		}
		packageNames[pkgName] = true

		// TODO: Handle import comments?
		// See https://cs.opensource.google/go/go/+/refs/tags/go1.17.2:src/go/build/build.go;drc=refs%2Ftags%2Fgo1.17.2;l=920

		// Check whether CGo is in use.
		isCGo := false
		for _, imp := range analysis.Imports {
			if imp == "C" {
				if isTest {
					pkg.InvalidGoFiles[name] = fmt.Sprintf("use of cgo in test %s not supported", name)
					continue
				}
				isCGo = true
			}
		}

		var fileList *[]string
		var importsMapForFile map[string]bool

		switch {
		case isCGo:
			// Ignore imports and embeds from cgo files since Pants does not support cgo.
			// TODO: When we do handle cgo, add a build tag for it.
			fileList = &pkg.IgnoredGoFiles
		case isXTest:
			fileList = &pkg.XTestGoFiles
			importsMapForFile = xtestImportsMap
		case isTest:
			fileList = &pkg.TestGoFiles
			importsMapForFile = testImportsMap
		default:
			fileList = &pkg.GoFiles
			importsMapForFile = importsMap
		}
		*fileList = append(*fileList, name)

		if importsMapForFile != nil {
			for _, importPath := range analysis.Imports {
				importsMapForFile[importPath] = true
			}
		}
	}

	// TODO: Add generated build tags (like `cgo` tag) to a field in package analysis?
	// Will probably need to vendor MatchFile (like rules_go does).

	for importPath, _ := range importsMap {
		pkg.Imports = append(pkg.Imports, importPath)
	}
	sort.Strings(pkg.Imports)

	for importPath, _ := range testImportsMap {
		pkg.TestImports = append(pkg.TestImports, importPath)
	}
	sort.Strings(pkg.Imports)

	for importPath, _ := range xtestImportsMap {
		pkg.XTestImports = append(pkg.XTestImports, importPath)
	}
	sort.Strings(pkg.XTestImports)

	// TODO: For cgo, add in .S/.sx files to SFiles.

	// Set the package name from the observed package name. There must only be one.
	var packageNamesList []string
	for pn, _ := range packageNames {
		packageNamesList = append(packageNamesList, pn)
	}
	if len(packageNamesList) == 1 {
		pkg.Name = packageNamesList[0]
	} else {
		return nil, fmt.Errorf("multiple package name encountered: %s", strings.Join(packageNamesList, ", "))
	}

	return pkg, nil
}

func main() {
	// TODO: Consider allowing caller to set build tags or platform? Setting platfor GOOS/GOARCH will be
	// necessary for multi-platform.
	buildContext := &build.Default

	for _, arg := range os.Args[1:] {
		pkg, err := analyzePackage(arg, buildContext)
		if err != nil {
			// TODO: Return an error in JSON form.
			fmt.Fprintf(os.Stderr, "Failed to analyze package: %s\n", err)
			os.Exit(1)
		}

		outputBytes, err := json.Marshal(pkg)
		if err != nil {
			// TODO: Return an error in JSON form.
			fmt.Fprintf(os.Stderr, "Failed to encode package metadata: %s\n", err)
			os.Exit(1)
		}
		_, err = os.Stdout.Write(outputBytes)
		if err != nil {
			// TODO: Return an error in JSON form.
			fmt.Fprintf(os.Stderr, "Failed to write package metadata: %s\n", err)
			os.Exit(1)
		}
	}

	os.Exit(0)
}
