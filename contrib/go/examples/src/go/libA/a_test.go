package libA

import (
  "testing"
)

func TestAdd(t *testing.T) {
  got, exp := Add(3, 4), 7
  if got != exp {
    t.Fatalf("got: %d, expected: %d", got, exp)
  }
}