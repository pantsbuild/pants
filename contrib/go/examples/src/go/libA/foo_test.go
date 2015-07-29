package libA

import (
  "testing"

  "github.com/fatih/set"
)

func TestAdd(t *testing.T) {
  got, exp := Add(3, 4), 7
  if got != exp {
    t.Errorf("got: %d, expected: %d", got, exp)
  }
}

func TestAddToSet(t *testing.T) {
  got, exp := SetSize(set.New(1, 2, 3)), 3
  if got != exp {
    t.Errorf("got: %d, expected: %d", got, exp)
  }
}