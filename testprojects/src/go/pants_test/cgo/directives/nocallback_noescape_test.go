package directives

import "testing"

func TestAddNumbersInC(t *testing.T) {
	if AddNumbersInC(1, 2) != 3 {
		t.Fail()
	}
}
