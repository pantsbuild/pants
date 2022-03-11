// Portions Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
//
// Adapted from Bazel rules_go go/tools/builders/{filter,read}.go and related files:
// https://github.com/bazelbuild/rules_go/blob/master/go/tools/builders/filter.go
// https://github.com/bazelbuild/rules_go/blob/master/go/tools/builders/read.go

// ORIGINAL LICENSE:

// Copyright 2012 The Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

// This file was adapted from Go src/go/build/read.go at commit 8634a234df2a
// on 2021-01-26. It's used to extract metadata from .go files without requiring
// them to be in the same directory.

package main

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"go/ast"
	"go/build"
	"go/build/constraint"
	"go/parser"
	"go/token"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// PANTS NOTE: These types were adaptd from https://github.com/bazelbuild/rules_go/blob/master/go/tools/builders/filter.go

type fileInfo struct {
	filename string
	ext      ext
	header   []byte
	fset     *token.FileSet
	parsed   *ast.File
	parseErr error
	matched  bool
	isCgo    bool
	pkg      string
	imports  []fileImport
	embeds   []fileEmbed
}

type ext int

type fileImport struct {
	path string
	pos  token.Pos
	doc  *ast.CommentGroup
}

type fileEmbed struct {
	pattern string
	pos     token.Position
}

// PANTS NOTE: The remainder of this file was copied from from https://github.com/bazelbuild/rules_go/blob/master/go/tools/builders/read.go

type importReader struct {
	b    *bufio.Reader
	buf  []byte
	peek byte
	err  error
	eof  bool
	nerr int
	pos  token.Position
}

func newImportReader(name string, r io.Reader) *importReader {
	return &importReader{
		b: bufio.NewReader(r),
		pos: token.Position{
			Filename: name,
			Line:     1,
			Column:   1,
		},
	}
}

func isIdent(c byte) bool {
	return 'A' <= c && c <= 'Z' || 'a' <= c && c <= 'z' || '0' <= c && c <= '9' || c == '_' || c >= utf8.RuneSelf
}

var (
	errSyntax = errors.New("syntax error")
	errNUL    = errors.New("unexpected NUL in input")
)

// syntaxError records a syntax error, but only if an I/O error has not already been recorded.
func (r *importReader) syntaxError() {
	if r.err == nil {
		r.err = errSyntax
	}
}

// readByte reads the next byte from the input, saves it in buf, and returns it.
// If an error occurs, readByte records the error in r.err and returns 0.
func (r *importReader) readByte() byte {
	c, err := r.b.ReadByte()
	if err == nil {
		r.buf = append(r.buf, c)
		if c == 0 {
			err = errNUL
		}
	}
	if err != nil {
		if err == io.EOF {
			r.eof = true
		} else if r.err == nil {
			r.err = err
		}
		c = 0
	}
	return c
}

// readByteNoBuf is like readByte but doesn't buffer the byte.
// It exhausts r.buf before reading from r.b.
func (r *importReader) readByteNoBuf() byte {
	var c byte
	var err error
	if len(r.buf) > 0 {
		c = r.buf[0]
		r.buf = r.buf[1:]
	} else {
		c, err = r.b.ReadByte()
		if err == nil && c == 0 {
			err = errNUL
		}
	}

	if err != nil {
		if err == io.EOF {
			r.eof = true
		} else if r.err == nil {
			r.err = err
		}
		return 0
	}
	r.pos.Offset++
	if c == '\n' {
		r.pos.Line++
		r.pos.Column = 1
	} else {
		r.pos.Column++
	}
	return c
}

// peekByte returns the next byte from the input reader but does not advance beyond it.
// If skipSpace is set, peekByte skips leading spaces and comments.
func (r *importReader) peekByte(skipSpace bool) byte {
	if r.err != nil {
		if r.nerr++; r.nerr > 10000 {
			panic("go/build: import reader looping")
		}
		return 0
	}

	// Use r.peek as first input byte.
	// Don't just return r.peek here: it might have been left by peekByte(false)
	// and this might be peekByte(true).
	c := r.peek
	if c == 0 {
		c = r.readByte()
	}
	for r.err == nil && !r.eof {
		if skipSpace {
			// For the purposes of this reader, semicolons are never necessary to
			// understand the input and are treated as spaces.
			switch c {
			case ' ', '\f', '\t', '\r', '\n', ';':
				c = r.readByte()
				continue

			case '/':
				c = r.readByte()
				if c == '/' {
					for c != '\n' && r.err == nil && !r.eof {
						c = r.readByte()
					}
				} else if c == '*' {
					var c1 byte
					for (c != '*' || c1 != '/') && r.err == nil {
						if r.eof {
							r.syntaxError()
						}
						c, c1 = c1, r.readByte()
					}
				} else {
					r.syntaxError()
				}
				c = r.readByte()
				continue
			}
		}
		break
	}
	r.peek = c
	return r.peek
}

// nextByte is like peekByte but advances beyond the returned byte.
func (r *importReader) nextByte(skipSpace bool) byte {
	c := r.peekByte(skipSpace)
	r.peek = 0
	return c
}

var goEmbed = []byte("go:embed")

// findEmbed advances the input reader to the next //go:embed comment.
// It reports whether it found a comment.
// (Otherwise it found an error or EOF.)
func (r *importReader) findEmbed(first bool) bool {
	// The import block scan stopped after a non-space character,
	// so the reader is not at the start of a line on the first call.
	// After that, each //go:embed extraction leaves the reader
	// at the end of a line.
	startLine := !first
	var c byte
	for r.err == nil && !r.eof {
		c = r.readByteNoBuf()
	Reswitch:
		switch c {
		default:
			startLine = false

		case '\n':
			startLine = true

		case ' ', '\t':
			// leave startLine alone

		case '"':
			startLine = false
			for r.err == nil {
				if r.eof {
					r.syntaxError()
				}
				c = r.readByteNoBuf()
				if c == '\\' {
					r.readByteNoBuf()
					if r.err != nil {
						r.syntaxError()
						return false
					}
					continue
				}
				if c == '"' {
					c = r.readByteNoBuf()
					goto Reswitch
				}
			}
			goto Reswitch

		case '`':
			startLine = false
			for r.err == nil {
				if r.eof {
					r.syntaxError()
				}
				c = r.readByteNoBuf()
				if c == '`' {
					c = r.readByteNoBuf()
					goto Reswitch
				}
			}

		case '/':
			c = r.readByteNoBuf()
			switch c {
			default:
				startLine = false
				goto Reswitch

			case '*':
				var c1 byte
				for (c != '*' || c1 != '/') && r.err == nil {
					if r.eof {
						r.syntaxError()
					}
					c, c1 = c1, r.readByteNoBuf()
				}
				startLine = false

			case '/':
				if startLine {
					// Try to read this as a //go:embed comment.
					for i := range goEmbed {
						c = r.readByteNoBuf()
						if c != goEmbed[i] {
							goto SkipSlashSlash
						}
					}
					c = r.readByteNoBuf()
					if c == ' ' || c == '\t' {
						// Found one!
						return true
					}
				}
			SkipSlashSlash:
				for c != '\n' && r.err == nil && !r.eof {
					c = r.readByteNoBuf()
				}
				startLine = true
			}
		}
	}
	return false
}

// readKeyword reads the given keyword from the input.
// If the keyword is not present, readKeyword records a syntax error.
func (r *importReader) readKeyword(kw string) {
	r.peekByte(true)
	for i := 0; i < len(kw); i++ {
		if r.nextByte(false) != kw[i] {
			r.syntaxError()
			return
		}
	}
	if isIdent(r.peekByte(false)) {
		r.syntaxError()
	}
}

// readIdent reads an identifier from the input.
// If an identifier is not present, readIdent records a syntax error.
func (r *importReader) readIdent() {
	c := r.peekByte(true)
	if !isIdent(c) {
		r.syntaxError()
		return
	}
	for isIdent(r.peekByte(false)) {
		r.peek = 0
	}
}

// readString reads a quoted string literal from the input.
// If an identifier is not present, readString records a syntax error.
func (r *importReader) readString() {
	switch r.nextByte(true) {
	case '`':
		for r.err == nil {
			if r.nextByte(false) == '`' {
				break
			}
			if r.eof {
				r.syntaxError()
			}
		}
	case '"':
		for r.err == nil {
			c := r.nextByte(false)
			if c == '"' {
				break
			}
			if r.eof || c == '\n' {
				r.syntaxError()
			}
			if c == '\\' {
				r.nextByte(false)
			}
		}
	default:
		r.syntaxError()
	}
}

// readImport reads an import clause - optional identifier followed by quoted string -
// from the input.
func (r *importReader) readImport() {
	c := r.peekByte(true)
	if c == '.' {
		r.peek = 0
	} else if isIdent(c) {
		r.readIdent()
	}
	r.readString()
}

// readComments is like io.ReadAll, except that it only reads the leading
// block of comments in the file.
func readComments(f io.Reader) ([]byte, error) {
	r := newImportReader("", f)
	r.peekByte(true)
	if r.err == nil && !r.eof {
		// Didn't reach EOF, so must have found a non-space byte. Remove it.
		r.buf = r.buf[:len(r.buf)-1]
	}
	return r.buf, r.err
}

// readGoInfo expects a Go file as input and reads the file up to and including the import section.
// It records what it learned in *info.
// If info.fset is non-nil, readGoInfo parses the file and sets info.parsed, info.parseErr,
// info.imports, info.embeds, and info.embedErr.
//
// It only returns an error if there are problems reading the file,
// not for syntax errors in the file itself.
func readGoInfo(f io.Reader, info *fileInfo) error {
	r := newImportReader(info.filename, f)

	r.readKeyword("package")
	r.readIdent()
	for r.peekByte(true) == 'i' {
		r.readKeyword("import")
		if r.peekByte(true) == '(' {
			r.nextByte(false)
			for r.peekByte(true) != ')' && r.err == nil {
				r.readImport()
			}
			r.nextByte(false)
		} else {
			r.readImport()
		}
	}

	info.header = r.buf

	// If we stopped successfully before EOF, we read a byte that told us we were done.
	// Return all but that last byte, which would cause a syntax error if we let it through.
	if r.err == nil && !r.eof {
		info.header = r.buf[:len(r.buf)-1]
	}

	// If we stopped for a syntax error, consume the whole file so that
	// we are sure we don't change the errors that go/parser returns.
	if r.err == errSyntax {
		r.err = nil
		for r.err == nil && !r.eof {
			r.readByte()
		}
		info.header = r.buf
	}
	if r.err != nil {
		return r.err
	}

	if info.fset == nil {
		return nil
	}

	// Parse file header & record imports.
	info.parsed, info.parseErr = parser.ParseFile(info.fset, info.filename, info.header, parser.ImportsOnly|parser.ParseComments)
	if info.parseErr != nil {
		return nil
	}
	info.pkg = info.parsed.Name.Name

	hasEmbed := false
	for _, decl := range info.parsed.Decls {
		d, ok := decl.(*ast.GenDecl)
		if !ok {
			continue
		}
		for _, dspec := range d.Specs {
			spec, ok := dspec.(*ast.ImportSpec)
			if !ok {
				continue
			}
			quoted := spec.Path.Value
			path, err := strconv.Unquote(quoted)
			if err != nil {
				return fmt.Errorf("parser returned invalid quoted string: <%s>", quoted)
			}
			if path == "embed" {
				hasEmbed = true
			}

			doc := spec.Doc
			if doc == nil && len(d.Specs) == 1 {
				doc = d.Doc
			}
			info.imports = append(info.imports, fileImport{path, spec.Pos(), doc})
		}
	}

	// If the file imports "embed",
	// we have to look for //go:embed comments
	// in the remainder of the file.
	// The compiler will enforce the mapping of comments to
	// declared variables. We just need to know the patterns.
	// If there were //go:embed comments earlier in the file
	// (near the package statement or imports), the compiler
	// will reject them. They can be (and have already been) ignored.
	if hasEmbed {
		var line []byte
		for first := true; r.findEmbed(first); first = false {
			line = line[:0]
			pos := r.pos
			for {
				c := r.readByteNoBuf()
				if c == '\n' || r.err != nil || r.eof {
					break
				}
				line = append(line, c)
			}
			// Add args if line is well-formed.
			// Ignore badly-formed lines - the compiler will report them when it finds them,
			// and we can pretend they are not there to help go list succeed with what it knows.
			embs, err := parseGoEmbed(string(line), pos)
			if err == nil {
				info.embeds = append(info.embeds, embs...)
			}
		}
	}

	return nil
}

// parseGoEmbed parses the text following "//go:embed" to extract the glob patterns.
// It accepts unquoted space-separated patterns as well as double-quoted and back-quoted Go strings.
// This is based on a similar function in cmd/compile/internal/gc/noder.go;
// this version calculates position information as well.
func parseGoEmbed(args string, pos token.Position) ([]fileEmbed, error) {
	trimBytes := func(n int) {
		pos.Offset += n
		pos.Column += utf8.RuneCountInString(args[:n])
		args = args[n:]
	}
	trimSpace := func() {
		trim := strings.TrimLeftFunc(args, unicode.IsSpace)
		trimBytes(len(args) - len(trim))
	}

	var list []fileEmbed
	for trimSpace(); args != ""; trimSpace() {
		var path string
		pathPos := pos
	Switch:
		switch args[0] {
		default:
			i := len(args)
			for j, c := range args {
				if unicode.IsSpace(c) {
					i = j
					break
				}
			}
			path = args[:i]
			trimBytes(i)

		case '`':
			i := strings.Index(args[1:], "`")
			if i < 0 {
				return nil, fmt.Errorf("invalid quoted string in //go:embed: %s", args)
			}
			path = args[1 : 1+i]
			trimBytes(1 + i + 1)

		case '"':
			i := 1
			for ; i < len(args); i++ {
				if args[i] == '\\' {
					i++
					continue
				}
				if args[i] == '"' {
					q, err := strconv.Unquote(args[:i+1])
					if err != nil {
						return nil, fmt.Errorf("invalid quoted string in //go:embed: %s", args[:i+1])
					}
					path = q
					trimBytes(i + 1)
					break Switch
				}
			}
			if i >= len(args) {
				return nil, fmt.Errorf("invalid quoted string in //go:embed: %s", args)
			}
		}

		if args != "" {
			r, _ := utf8.DecodeRuneInString(args)
			if !unicode.IsSpace(r) {
				return nil, fmt.Errorf("invalid quoted string in //go:embed: %s", args)
			}
		}
		list = append(list, fileEmbed{path, pathPos})
	}
	return list, nil
}

// goodOSArchFile returns false if the name contains a $GOOS or $GOARCH
// suffix which does not match the current system.
// The recognized name formats are:
//
//     name_$(GOOS).*
//     name_$(GOARCH).*
//     name_$(GOOS)_$(GOARCH).*
//     name_$(GOOS)_test.*
//     name_$(GOARCH)_test.*
//     name_$(GOOS)_$(GOARCH)_test.*
//
// Exceptions:
// if GOOS=android, then files with GOOS=linux are also matched.
// if GOOS=illumos, then files with GOOS=solaris are also matched.
// if GOOS=ios, then files with GOOS=darwin are also matched.
func goodOSArchFile(ctxt *build.Context, name string, allTags map[string]bool) bool {
	name, _, _ = stringsCut(name, ".")

	// Before Go 1.4, a file called "linux.go" would be equivalent to having a
	// build tag "linux" in that file. For Go 1.4 and beyond, we require this
	// auto-tagging to apply only to files with a non-empty prefix, so
	// "foo_linux.go" is tagged but "linux.go" is not. This allows new operating
	// systems, such as android, to arrive without breaking existing code with
	// innocuous source code in "android.go". The easiest fix: cut everything
	// in the name before the initial _.
	i := strings.Index(name, "_")
	if i < 0 {
		return true
	}
	name = name[i:] // ignore everything before first _

	l := strings.Split(name, "_")
	if n := len(l); n > 0 && l[n-1] == "test" {
		l = l[:n-1]
	}
	n := len(l)
	if n >= 2 && knownOS[l[n-2]] && knownArch[l[n-1]] {
		return matchTag(ctxt, l[n-1], allTags) && matchTag(ctxt, l[n-2], allTags)
	}
	if n >= 1 && (knownOS[l[n-1]] || knownArch[l[n-1]]) {
		return matchTag(ctxt, l[n-1], allTags)
	}
	return true
}

var knownOS = make(map[string]bool)
var knownArch = make(map[string]bool)

func init() {
	for _, v := range strings.Fields(goosList) {
		knownOS[v] = true
	}
	for _, v := range strings.Fields(goarchList) {
		knownArch[v] = true
	}
}

// matchFile determines whether the file with the given name in the given directory
// should be included in the package being constructed.
// If the file should be included, matchFile returns a non-nil *fileInfo (and a nil error).
// Non-nil errors are reserved for unexpected problems.
//
// If name denotes a Go program, matchFile reads until the end of the
// imports and returns that section of the file in the fileInfo's header field,
// even though it only considers text until the first non-comment
// for +build lines.
//
// If allTags is non-nil, matchFile records any encountered build tag
// by setting allTags[tag] = true.
func matchFile(ctxt *build.Context, dir, name string, allTags map[string]bool, binaryOnly *bool, fset *token.FileSet) (*fileInfo, error) {
	if strings.HasPrefix(name, "_") ||
		strings.HasPrefix(name, ".") {
		return nil, nil
	}

	i := strings.LastIndex(name, ".")
	if i < 0 {
		i = len(name)
	}
	ext := name[i:]

	if !goodOSArchFile(ctxt, name, allTags) && !ctxt.UseAllFiles {
		return nil, nil
	}

	var dummyPkg Package
	if ext != ".go" && fileListForExt(&dummyPkg, ext) == nil {
		// skip
		return nil, nil
	}

	info := &fileInfo{filename: filepath.Join(dir, name), fset: fset}
	if ext == ".syso" {
		// binary, no reading
		return info, nil
	}

	f, err := os.Open(info.filename)
	if err != nil {
		return nil, err
	}

	if strings.HasSuffix(name, ".go") {
		err = readGoInfo(f, info)
		if strings.HasSuffix(name, "_test.go") {
			binaryOnly = nil // ignore //go:binary-only-package comments in _test.go files
		}
	} else {
		binaryOnly = nil // ignore //go:binary-only-package comments in non-Go sources
		info.header, err = readComments(f)
	}
	f.Close()
	if err != nil {
		return nil, fmt.Errorf("read %s: %v", info.filename, err)
	}

	// Look for +build comments to accept or reject the file.
	ok, sawBinaryOnly, err := shouldBuild(ctxt, info.header, allTags)
	if err != nil {
		return nil, fmt.Errorf("%s: %v", name, err)
	}
	if !ok && !ctxt.UseAllFiles {
		return nil, nil
	}

	if binaryOnly != nil && sawBinaryOnly {
		*binaryOnly = true
	}

	return info, nil
}

var (
	bSlashSlash = []byte("//")
	bStarSlash  = []byte("/*")
	bSlashStar  = []byte("*/")
	bPlusBuild  = []byte("+build")
	newline     = []byte("\n")

	goBuildComment = []byte("//go:build")

	errGoBuildWithoutBuild = errors.New("//go:build comment without // +build comment")
	errMultipleGoBuild     = errors.New("multiple //go:build comments")
)

func isGoBuildComment(line []byte) bool {
	if !bytes.HasPrefix(line, goBuildComment) {
		return false
	}
	line = bytes.TrimSpace(line)
	rest := line[len(goBuildComment):]
	return len(rest) == 0 || len(bytes.TrimSpace(rest)) < len(rest)
}

// Special comment denoting a binary-only package.
// See https://golang.org/design/2775-binary-only-packages
// for more about the design of binary-only packages.
var binaryOnlyComment = []byte("//go:binary-only-package")

// shouldBuild reports whether it is okay to use this file,
// The rule is that in the file's leading run of // comments
// and blank lines, which must be followed by a blank line
// (to avoid including a Go package clause doc comment),
// lines beginning with '// +build' are taken as build directives.
//
// The file is accepted only if each such line lists something
// matching the file. For example:
//
//      // +build windows linux
//
// marks the file as applicable only on Windows and Linux.
//
// For each build tag it consults, shouldBuild sets allTags[tag] = true.
//
// shouldBuild reports whether the file should be built
// and whether a //go:binary-only-package comment was found.
func shouldBuild(ctxt *build.Context, content []byte, allTags map[string]bool) (shouldBuild, binaryOnly bool, err error) {
	// Identify leading run of // comments and blank lines,
	// which must be followed by a blank line.
	// Also identify any //go:build comments.
	content, goBuild, sawBinaryOnly, err := parseFileHeader(content)
	if err != nil {
		return false, false, err
	}

	// If //go:build line is present, it controls.
	// Otherwise fall back to +build processing.
	switch {
	case goBuild != nil:
		x, err := constraint.Parse(string(goBuild))
		if err != nil {
			return false, false, fmt.Errorf("parsing //go:build line: %v", err)
		}
		shouldBuild = eval(ctxt, x, allTags)

	default:
		shouldBuild = true
		p := content
		for len(p) > 0 {
			line := p
			if i := bytes.IndexByte(line, '\n'); i >= 0 {
				line, p = line[:i], p[i+1:]
			} else {
				p = p[len(p):]
			}
			line = bytes.TrimSpace(line)
			if !bytes.HasPrefix(line, bSlashSlash) || !bytes.Contains(line, bPlusBuild) {
				continue
			}
			text := string(line)
			if !constraint.IsPlusBuild(text) {
				continue
			}
			if x, err := constraint.Parse(text); err == nil {
				if !eval(ctxt, x, allTags) {
					shouldBuild = false
				}
			}
		}
	}

	return shouldBuild, sawBinaryOnly, nil
}

func parseFileHeader(content []byte) (trimmed, goBuild []byte, sawBinaryOnly bool, err error) {
	end := 0
	p := content
	ended := false       // found non-blank, non-// line, so stopped accepting // +build lines
	inSlashStar := false // in /* */ comment

Lines:
	for len(p) > 0 {
		line := p
		if i := bytes.IndexByte(line, '\n'); i >= 0 {
			line, p = line[:i], p[i+1:]
		} else {
			p = p[len(p):]
		}
		line = bytes.TrimSpace(line)
		if len(line) == 0 && !ended { // Blank line
			// Remember position of most recent blank line.
			// When we find the first non-blank, non-// line,
			// this "end" position marks the latest file position
			// where a // +build line can appear.
			// (It must appear _before_ a blank line before the non-blank, non-// line.
			// Yes, that's confusing, which is part of why we moved to //go:build lines.)
			// Note that ended==false here means that inSlashStar==false,
			// since seeing a /* would have set ended==true.
			end = len(content) - len(p)
			continue Lines
		}
		if !bytes.HasPrefix(line, bSlashSlash) { // Not comment line
			ended = true
		}

		if !inSlashStar && isGoBuildComment(line) {
			if goBuild != nil {
				return nil, nil, false, errMultipleGoBuild
			}
			goBuild = line
		}
		if !inSlashStar && bytes.Equal(line, binaryOnlyComment) {
			sawBinaryOnly = true
		}
	Comments:
		for len(line) > 0 {
			if inSlashStar {
				if i := bytes.Index(line, bStarSlash); i >= 0 {
					inSlashStar = false
					line = bytes.TrimSpace(line[i+len(bStarSlash):])
					continue Comments
				}
				continue Lines
			}
			if bytes.HasPrefix(line, bSlashSlash) {
				continue Lines
			}
			if bytes.HasPrefix(line, bSlashStar) {
				inSlashStar = true
				line = bytes.TrimSpace(line[len(bSlashStar):])
				continue Comments
			}
			// Found non-comment text.
			break Lines
		}
	}

	return content[:end], goBuild, sawBinaryOnly, nil
}
