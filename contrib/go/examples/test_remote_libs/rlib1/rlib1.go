package rlib1

import (
  "fmt"

  "github.com/fakeuser/rlib3"
  "github.com/fakeuser/rlib4"
)

func Speak() {
  fmt.Println("Hello from rlib1!")
  rlib3.Speak()
  rlib4.Speak()
  fmt.Println("Bye from rlib1!")
}