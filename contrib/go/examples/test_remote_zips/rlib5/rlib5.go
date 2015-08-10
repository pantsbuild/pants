package rlib5

import (
  "fmt"

  // Intent is for this library to not have a declared BUILD file.
  "github.com/fakeuser/rlib6"
)

func Speak() {
  fmt.Println("Hello from rlib5!")
  rlib6.Speak()
  fmt.Println("Bye from rlib5!")
}
