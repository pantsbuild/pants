package libA

import (
  "github.com/fatih/set"
  "github.com/gorilla/mux"

  "contrib/go/examples/src/go/libB"
  "contrib/go/examples/src/go/libC"
)

func Speak() {
  println("Hello from libA!")
  libB.Speak()
  libC.Speak()
  println("Bye from libA!")
}

func Add(a int, b int) int {
  return a + b
}

func Size(s *set.Set) int {
  mux.NewRouter()
  return s.Size()
}