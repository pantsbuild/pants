package rlib3

import (
  "fmt"

  "github.com/fakeuser/rlib4"
)

func Speak() {
  fmt.Println("Hello from rlib3!")
  rlib4.Speak()
  fmt.Println("Bye from rlib3!")
}