package libA

import (
  "flag"
  "testing"

  "github.com/fatih/set"
)

var xfail = flag.Bool("xfail", false, "expect failure")

func TestAdd(t *testing.T) {
  got, exp := Add(3, 4), 7
  assertEq(t, got, exp)
}

func TestSetSize(t *testing.T) {
  got, exp := SetSize(set.New(1, 2, 3)), 3
  assertEq(t, got, exp)
}

func assertEq(t *testing.T, got int, exp int) {
  if got != exp && !*xfail {
    t.Errorf("got: %d, expected: %d", got, exp)
  } else if got == exp && *xfail {
    t.Errorf("expected failure")
  }
}