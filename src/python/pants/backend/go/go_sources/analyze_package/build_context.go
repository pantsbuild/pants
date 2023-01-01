/* Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package main

import (
	"go/build"
	"go/build/constraint"
	"strings"
)

// ORIGINAL LICENSE:
//
// Copyright 2011 The Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.
//
// This file was adapted from Go src/go/build/build.go at commit 7c694fbad1ed6f2f825fd09cf7a86da3be549cea
// on 2022-02-25.

// matchTag reports whether the name is one of:
//
//      cgo (if cgo is enabled)
//      $GOOS
//      $GOARCH
//      ctxt.Compiler
//      linux (if GOOS = android)
//      solaris (if GOOS = illumos)
//      tag (if tag is listed in ctxt.BuildTags or ctxt.ReleaseTags)
//
// It records all consulted tags in allTags.
func matchTag(ctxt *build.Context, name string, allTags map[string]bool) bool {
	if allTags != nil {
		allTags[name] = true
	}

	// special tags
	if ctxt.CgoEnabled && name == "cgo" {
		return true
	}
	if name == ctxt.GOOS || name == ctxt.GOARCH || name == ctxt.Compiler {
		return true
	}
	if ctxt.GOOS == "android" && name == "linux" {
		return true
	}
	if ctxt.GOOS == "illumos" && name == "solaris" {
		return true
	}
	if ctxt.GOOS == "ios" && name == "darwin" {
		return true
	}

	// other tags
	for _, tag := range ctxt.BuildTags {
		if tag == name {
			return true
		}
	}
	toolTags := extractToolTags(ctxt)
	for _, tag := range toolTags {
		if tag == name {
			return true
		}
	}
	for _, tag := range ctxt.ReleaseTags {
		if tag == name {
			return true
		}
	}

	return false
}

func eval(ctxt *build.Context, x constraint.Expr, allTags map[string]bool) bool {
	return x.Eval(func(tag string) bool { return matchTag(ctxt, tag, allTags) })
}

// matchAuto interprets text as either a +build or //go:build expression (whichever works),
// reporting whether the expression matches the build context.
//
// matchAuto is only used for testing of tag evaluation
// and in #cgo lines, which accept either syntax.
func matchAuto(ctxt *build.Context, text string, allTags map[string]bool) bool {
	if strings.ContainsAny(text, "&|()") {
		text = "//go:build " + text
	} else {
		text = "// +build " + text
	}
	x, err := constraint.Parse(text)
	if err != nil {
		return false
	}
	return eval(ctxt, x, allTags)
}
