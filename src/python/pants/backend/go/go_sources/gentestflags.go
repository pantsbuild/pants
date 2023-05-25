// Script used to generate the TEST_FLAGS constant for the Pants test rules.
// Run: `go run ./gentestflags.go` and copy the output as directed in test.py.

// Based on logic from https://github.com/golang/go/blob/master/src/cmd/go/internal/test/genflags.go
// used under BSD license.

//go:build ignore
// +build ignore

package main

import (
	"bytes"
	"flag"
	"log"
	"os"
	"strings"
	"testing"
	"text/template"
)

func main() {
	if err := generate(); err != nil {
		log.Fatal(err)
	}
}

func generate() error {
	t := template.Must(template.New("fileTemplate").Parse(fileTemplate))
	tData := map[string]interface{}{
		"testFlags": testFlags(),
	}
	buf := bytes.NewBuffer(nil)
	if err := t.Execute(buf, tData); err != nil {
		return err
	}

	_, err := os.Stdout.Write(buf.Bytes())
	return err
}

type boolFlag interface {
	flag.Value
	IsBoolFlag() bool
}

func testFlags() map[string]bool {
	testing.Init()

	names := make(map[string]bool)
	flag.VisitAll(func(f *flag.Flag) {
		if !strings.HasPrefix(f.Name, "test.") {
			return
		}
		name := strings.TrimPrefix(f.Name, "test.")

		switch name {
		case "testlogfile", "paniconexit0", "fuzzcachedir", "fuzzworker", "gocoverdir":
		// These flags are only for use by cmd/go.
		default:
			expectsValue := true
			if fv, ok := f.Value.(boolFlag); ok && fv.IsBoolFlag() {
				expectsValue = false
			}
			names[name] = expectsValue
		}
	})

	return names
}

const fileTemplate = `TEST_FLAGS = {
{{- range $name, $expects_value := .testFlags}}
	"{{$name}}": {{if $expects_value}}True{{else}}False{{end}},
{{- end }}
}
`
