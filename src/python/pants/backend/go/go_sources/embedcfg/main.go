/* Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

/*
 * Match embed patterns against files.
 * Based in part on Bazel rules_go:
 * https://github.com/bazelbuild/rules_go/blob/bd7fbccc635af297db7b36f6c81d0e7db7921cca/go/tools/builders/embedcfg.go
 */

package main

import (
    "encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"io/ioutil"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

type Patterns struct {
	EmbedPatterns      []string `json:",omitempty"` // patterns from GoFiles, CgoFiles
	TestEmbedPatterns  []string `json:",omitempty"` // patterns from TestGoFiles
	XTestEmbedPatterns []string `json:",omitempty"` // patterns from XTestGoFiles
}

type EmbedCfg struct {
	Patterns map[string][]string
	Files    map[string]string
}

type EmbedConfigs struct {
	EmbedConfig      *EmbedCfg `json:",omitempty"` // files matching the EmbedPatterns
	TestEmbedConfig  *EmbedCfg `json:",omitempty"` // files matching the TestEmbedPatterns
	XTestEmbedConfig *EmbedCfg `json:",omitempty"` // files matching the XTestEmbedPatterns
}

// findInRootDirs returns a string from rootDirs which is a parent of the
// file path p. If there is no such string, findInRootDirs returns "".
func findInRootDirs(p string, rootDirs []string) string {
	dir := filepath.Dir(p)
	for _, rootDir := range rootDirs {
		if rootDir == dir ||
			(strings.HasPrefix(dir, rootDir) && len(dir) > len(rootDir)+1 && dir[len(rootDir)] == filepath.Separator) {
			return rootDir
		}
	}
	return ""
}

// embedNode represents an embeddable file or directory in a tree.
type embedNode struct {
	name       string                // base name
	path       string                // full file path relative to the base package directory
	children   map[string]*embedNode // non-nil for directory
	childNames []string              // sorted
}

// add inserts file nodes into the tree rooted at f for the slash-separated
// path src, relative to the absolute file path rootDir. If src points to a
// directory, add recursively inserts nodes for its contents. If a node already
// exists (for example, if a source file and a generated file have the same
// name), add leaves the existing node in place.
func (n *embedNode) add(rootDir, src string) error {
	// Create nodes for parents of src.
	parent := n
	parts := strings.Split(src, "/")
	for _, p := range parts[:len(parts)-1] {
		if parent.children[p] == nil {
			parent.children[p] = &embedNode{
				name:     p,
				children: make(map[string]*embedNode),
			}
		}
		parent = parent.children[p]
	}

	// Create a node for src. If src is a directory, recursively create nodes for
	// its contents. Go embedding ignores symbolic links, and they are ignored here
	// as well.
	// TODO: Actually ignore symbolic links.
	var visit func(*embedNode, string, os.FileInfo) error
	visit = func(parent *embedNode, path string, fi os.FileInfo) error {
		base := filepath.Base(path)
		if parent.children[base] == nil {
			parent.children[base] = &embedNode{name: base, path: path}
		}
		if !fi.IsDir() {
			return nil
		}
		node := parent.children[base]
		node.children = make(map[string]*embedNode)
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		names, err := f.Readdirnames(0)
		f.Close()
		if err != nil {
			return err
		}
		for _, name := range names {
			cPath := filepath.Join(path, name)
			cfi, err := os.Stat(cPath)
			if err != nil {
				return err
			}
			if err := visit(node, cPath, cfi); err != nil {
				return err
			}
		}
		return nil
	}

	path := filepath.Join(rootDir, src)
	fi, err := os.Stat(path)
	if err != nil {
		return err
	}
	return visit(parent, path, fi)
}

func (n *embedNode) isDir() bool {
	return n.children != nil
}

// get returns a tree node, given a slash-separated path relative to the
// receiver. get returns nil if no node exists with that path.
func (n *embedNode) get(path string) *embedNode {
	if path == "." || path == "" {
		return n
	}
	for _, part := range strings.Split(path, "/") {
		n = n.children[part]
		if n == nil {
			return nil
		}
	}
	return n
}

var errSkip = errors.New("skip")

// walk calls fn on each node in the tree rooted at n in depth-first pre-order.
func (n *embedNode) walk(fn func(rel string, n *embedNode) error) error {
	var visit func(string, *embedNode) error
	visit = func(rel string, node *embedNode) error {
		err := fn(rel, node)
		if err == errSkip {
			return nil
		} else if err != nil {
			return err
		}
		for _, name := range node.childNames {
			if err := visit(path.Join(rel, name), node.children[name]); err != nil && err != errSkip {
				return err
			}
		}
		return nil
	}
	err := visit("", n)
	if err == errSkip {
		return nil
	}
	return err
}

// buildEmbedTree constructs a logical directory tree of embeddable files.
func buildEmbedTree(embedSrcs, embedRootDirs []string) (root *embedNode, err error) {
	defer func() {
		if err != nil {
			err = fmt.Errorf("building tree of embeddable files in directories %s: %v", strings.Join(embedRootDirs, string(filepath.ListSeparator)), err)
		}
	}()
	// Add each path to the tree.
	root = &embedNode{name: "", children: make(map[string]*embedNode)}
	for _, src := range embedSrcs {
		rootDir := findInRootDirs(src, embedRootDirs)
		if rootDir == "" {
			// Embedded path cannot be matched by any valid pattern. Ignore.
			continue
		}
		rel := filepath.ToSlash(src[len(rootDir)+1:])
		if err := root.add(rootDir, rel); err != nil {
			return nil, err
		}
	}

	// Sort children in each directory node.
	var visit func(*embedNode)
	visit = func(node *embedNode) {
		node.childNames = make([]string, 0, len(node.children))
		for name, child := range node.children {
			node.childNames = append(node.childNames, name)
			visit(child)
		}
		sort.Strings(node.childNames)
	}
	visit(root)

	return root, nil
}

// resolveEmbed matches a //go:embed pattern in a source file to a set of
// embeddable files in the given tree.
func resolveEmbed(pattern string, root *embedNode) (matchedPaths, matchedFiles []string, err error) {
	defer func() {
		if err != nil {
			err = fmt.Errorf("could not embed %s: %v", pattern, err)
		}
	}()

	// Check that the pattern has valid syntax.
	if _, err := path.Match(pattern, ""); err != nil || !validEmbedPattern(pattern) {
		return nil, nil, fmt.Errorf("invalid pattern syntax")
	}

	// Search for matching files.
	err = root.walk(func(matchRel string, matchNode *embedNode) error {
		if ok, _ := path.Match(pattern, matchRel); !ok {
			// Non-matching file or directory.
			return nil
		}
		if !matchNode.isDir() {
			// Matching file. Add to list.
			matchedPaths = append(matchedPaths, matchRel)
			matchedFiles = append(matchedFiles, matchNode.path)
			return nil
		}

		// Matching directory. Recursively add all files in subdirectories.
		// Don't add hidden files or directories (starting with "." or "_").
		// See golang/go#42328.
		matchTreeErr := matchNode.walk(func(childRel string, childNode *embedNode) error {
			if childRel != "" {
				if base := path.Base(childRel); strings.HasPrefix(base, ".") || strings.HasPrefix(base, "_") {
					return errSkip
				}
			}
			if !childNode.isDir() {
				matchedPaths = append(matchedPaths, path.Join(matchRel, childRel))
				matchedFiles = append(matchedFiles, childNode.path)
			}
			return nil
		})
		if matchTreeErr != nil {
			return matchTreeErr
		}
		return errSkip
	})
	if err != nil && err != errSkip {
		return nil, nil, err
	}
	if len(matchedPaths) == 0 {
		return nil, nil, fmt.Errorf("no matching files found")
	}
	return matchedPaths, matchedFiles, nil
}

func validEmbedPattern(pattern string) bool {
	return pattern != "." && fsValidPath(pattern)
}

// validPath reports whether the given path name
// is valid for use in a call to Open.
// Path names passed to open are unrooted, slash-separated
// sequences of path elements, like “x/y/z”.
// Path names must not contain a “.” or “..” or empty element,
// except for the special case that the root directory is named “.”.
//
// Paths are slash-separated on all systems, even Windows.
// Backslashes must not appear in path names.
//
// Copied from io/fs.ValidPath in Go 1.16beta1.
func fsValidPath(name string) bool {
	if name == "." {
		// special case
		return true
	}

	// Iterate over elements in name, checking each.
	for {
		i := 0
		for i < len(name) && name[i] != '/' {
			if name[i] == '\\' {
				return false
			}
			i++
		}
		elem := name[:i]
		if elem == "" || elem == "." || elem == ".." {
			return false
		}
		if i == len(name) {
			return true // reached clean ending
		}
		name = name[i+1:]
	}
}

func computeEmbedConfigs(directory string, patterns *Patterns) (*EmbedConfigs, error) {
	// Obtain a list of files in and under the package's directory. These will be embeddable files.
	// TODO: Support resource targets elsewhere in the repository.

	configs := &EmbedConfigs{}

	var embedSrcs []string
	err := filepath.WalkDir(directory, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		embedSrcs = append(embedSrcs, path)
		return nil
	})
	if err != nil {
		return nil, err
	}

	root, err := buildEmbedTree(embedSrcs, []string{directory})
	if err != nil {
		return nil, err
	}

	if len(patterns.EmbedPatterns) > 0 {
		embedCfg := &EmbedCfg{
			Patterns: make(map[string][]string),
			Files:    make(map[string]string),
		}

		for _, pattern := range patterns.EmbedPatterns {
			matchedPaths, matchedFiles, err := resolveEmbed(pattern, root)
			if err != nil {
				return nil, err
			}
			embedCfg.Patterns[pattern] = matchedPaths
			for i, rel := range matchedPaths {
				embedCfg.Files[rel] = matchedFiles[i]
			}
		}

		configs.EmbedConfig = embedCfg
	}

	if len(patterns.TestEmbedPatterns) > 0 {
		embedCfg := &EmbedCfg{
			Patterns: make(map[string][]string),
			Files:    make(map[string]string),
		}
		if configs.EmbedConfig != nil {
			for key, value := range configs.EmbedConfig.Patterns {
				embedCfg.Patterns[key] = value
			}
			for key, value := range configs.EmbedConfig.Files {
				embedCfg.Files[key] = value
			}
		}

		for _, pattern := range patterns.TestEmbedPatterns {
			matchedPaths, matchedFiles, err := resolveEmbed(pattern, root)
			if err != nil {
				return nil, err
			}
			embedCfg.Patterns[pattern] = matchedPaths
			for i, rel := range matchedPaths {
				embedCfg.Files[rel] = matchedFiles[i]
			}
		}

		configs.TestEmbedConfig = embedCfg
	}

	if len(patterns.XTestEmbedPatterns) > 0 {
		embedCfg := &EmbedCfg{
			Patterns: make(map[string][]string),
			Files:    make(map[string]string),
		}

		for _, pattern := range patterns.XTestEmbedPatterns {
			matchedPaths, matchedFiles, err := resolveEmbed(pattern, root)
			if err != nil {
				return nil, err
			}
			embedCfg.Patterns[pattern] = matchedPaths
			for i, rel := range matchedPaths {
				embedCfg.Files[rel] = matchedFiles[i]
			}
		}

		configs.XTestEmbedConfig = embedCfg
	}

	return configs, nil
}

func main() {
	data, err := ioutil.ReadFile(os.Args[1])
	if err != nil {
		fmt.Printf("{\"Error\": \"Failed to open input JSON: %s\"}", err)
		os.Exit(1)
	}

	var patterns Patterns
	err = json.Unmarshal(data, &patterns)
	if err != nil {
		fmt.Printf("{\"Error\": \"Failed to deserialize JSON: %s\"}", err)
		os.Exit(1)
	}

	result, err := computeEmbedConfigs("__resources__", &patterns)
	if err != nil {
		fmt.Printf("{\"Error\": \"Failed to find embedded resources: %s\"}", err)
		os.Exit(1)
	}

	outputBytes, err := json.Marshal(result)
	if err != nil {
		fmt.Printf("{\"Error\": \"Failed to encode embed config: %s\"}", err)
		os.Exit(1)
	}
	_, err = os.Stdout.Write(outputBytes)
	if err != nil {
		fmt.Printf("{\"Error\": \"Failed to write embed config: %s\"}", err)
		os.Exit(1)
	}
	os.Exit(0)
}
