// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package main

import (
	"github.com/golang/protobuf/proto"
	"pantsbuild/example/distance"
	"pantsbuild/example/route"
)

func main() {
	r := &route.Route{
		Name: proto.String("example_route"),
		Distances: []*distance.Distance{
			{
				Unit:   proto.String("parsecs"),
				Number: proto.Int64(27),
			},
			{
				Unit:   proto.String("mm"),
				Number: proto.Int64(2),
			},
		},
	}
	println(r.String())
}
