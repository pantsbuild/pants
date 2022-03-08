//go:build go1.17

/* Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package main

import (
	"go/build"
)

func extractToolTags(ctxt *build.Context) []string {
	return ctxt.ToolTags
}
