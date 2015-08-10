package main

import (
  "fmt"

  "github.com/fakeuser/rlib1"
  "github.com/fakeuser/rlib2"
)

func main() {
  fmt.Println("Hello from main!")
  rlib1.Speak()
  rlib2.Speak()
  fmt.Println("Bye from main!")
}