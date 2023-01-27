/* Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package main

import (
	"bytes"
	"fmt"
	"os"
)

func maybeGolangAssembly(filename string) (bool, error) {
	data, err := os.ReadFile(filename)
	if err != nil {
		return false, err
	}

	if bytes.HasPrefix(data, []byte("TEXT")) || bytes.Contains(data, []byte("\nTEXT")) ||
		bytes.HasPrefix(data, []byte("DATA")) || bytes.Contains(data, []byte("\nDATA")) ||
		bytes.HasPrefix(data, []byte("GLOBL")) || bytes.Contains(data, []byte("\nGLOBL")) {
		return true, nil
	}

	return false, nil
}

func main() {
	if len(os.Args) >= 2 {
		for _, arg := range os.Args[1:] {
			found, err := maybeGolangAssembly(arg)
			if err != nil {
				fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
				os.Exit(1)
			}

			if found {
				fmt.Printf("%s\n", arg)
			}
		}
	}
}
