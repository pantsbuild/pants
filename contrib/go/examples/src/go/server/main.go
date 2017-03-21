package main

import (
	"fmt"
	"html"
	"net/http"

	"github.com/gorilla/mux"
	"golang.org/x/net/http2"
	"google.golang.org/grpc"
	"gopkg.in/yaml.v2"
)

func main() {
	// Some dummy dependencies, to make sure we know how to buildgen and fetch them.
	_ = http2.TrailerPrefix
	_ = grpc.CustomCodec
	_ = yaml.Marshal

	r := mux.NewRouter()
	r.HandleFunc("/", func(rw http.ResponseWriter, req *http.Request) {
		fmt.Fprintf(rw, "Hello, %q", html.EscapeString(req.URL.Path))
	})
	// Don't actually use the router or start a server -- just do enough
	// so all variables + packages are being used or else the Go compiler
	// will complain.
}
