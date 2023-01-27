/* Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package main

/*
 * Adapted from https://github.com/golang/go/blob/d45df06663c88984b75052fd0631974916b1bddb/src/cmd/go/internal/modload/vendor.go
 * Original License:
 *  // Copyright 2020 The Go Authors. All rights reserved.
 *  // Use of this source code is governed by a BSD-style
 *  // license that can be found in the LICENSE file.
 */

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

type Version struct {
	Path    string `json:"path"`
	Version string `json:"version"`
}

type Module struct {
	ModVersion         Version  `json:"mod_version"`
	PackageImportPaths []string `json:"package_import_paths,omitempty"`
	Explicit           bool     `json:"explicit"`
	GoVersion          string   `json:"go_version"`
	Replacement        Version  `json:"replacement"`
}

// CutPrefix returns s without the provided leading prefix string
// and reports whether it found the prefix.
// If s doesn't start with prefix, CutPrefix returns s, false.
// If prefix is the empty string, CutPrefix returns s, true.
func CutPrefix(s, prefix string) (after string, found bool) {
	if !strings.HasPrefix(s, prefix) {
		return s, false
	}
	return s[len(prefix):], true
}

func parseVendoredModuleList(path string) ([]Module, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var modules []Module
	var mod Module

	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "# ") {
			f := strings.Fields(line)

			if len(f) < 3 {
				continue
			}
			if IsValidSemver(f[2]) {
				// A module, but we don't yet know whether it is in the build list or
				// only included to indicate a replacement.
				if mod.ModVersion.Path != "" {
					modules = append(modules, mod)
				}
				mod = Module{ModVersion: Version{Path: f[1], Version: f[2]}}
				f = f[3:]
			} else if f[2] == "=>" {
				// A wildcard replacement found in the main module's go.mod file.
				if mod.ModVersion.Path != "" {
					modules = append(modules, mod)
				}
				mod = Module{ModVersion: Version{Path: f[1]}}
				f = f[2:]
			} else {
				// Not a version or a wildcard replacement.
				// We don't know how to interpret this module line, so ignore it.
				mod = Module{}
				continue
			}

			if len(f) >= 2 && f[0] == "=>" {
				if len(f) == 2 {
					// File replacement.
					mod.Replacement = Version{Path: f[1]}
				} else if len(f) == 3 && IsValidSemver(f[2]) {
					// Path and version replacement.
					mod.Replacement = Version{Path: f[1], Version: f[2]}
				} else {
					// We don't understand this replacement. Ignore it.
				}
			}
			continue
		}

		// Not a module line. Must be a package within a module or a metadata
		// directive, either of which requires a preceding module line.
		if mod.ModVersion.Path == "" {
			continue
		}

		if annonations, ok := CutPrefix(line, "## "); ok {
			// Metadata. Take the union of annotations across multiple lines, if present.
			for _, entry := range strings.Split(annonations, ";") {
				entry = strings.TrimSpace(entry)
				if entry == "explicit" {
					mod.Explicit = true
				}
				if goVersion, ok := CutPrefix(entry, "go "); ok {
					mod.GoVersion = goVersion
				}
				// All other tokens are reserved for future use.
			}
			continue
		}

		// TODO: Actually port CheckImportPath impl over from `go` sources.
		if f := strings.Fields(line); len(f) == 1 /* && module.CheckImportPath(f[0]) == nil */ {
			// A package within the current module.
			mod.PackageImportPaths = append(mod.PackageImportPaths, f[0])
		}
	}

	if mod.ModVersion.Path != "" {
		modules = append(modules, mod)
	}

	return modules, nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, "ERROR: Not enough arguments.\n")
		os.Exit(1)
	}

	modules, err := parseVendoredModuleList(os.Args[1])
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: Failed to parse `%s`: %s\n", os.Args[1], err)
		os.Exit(1)
	}

	outputBytes, err := json.Marshal(modules)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: Failed to encode parswd modules: %v\n", err)
		os.Exit(1)
	}

	_, err = os.Stdout.Write(outputBytes)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: Failed to write JSON: %v\n", err)
		os.Exit(1)
	}
}
