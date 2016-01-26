package usethrift

import "thrifttest/duck"

func whatevs() string {
	d := duck.NewDuck()
	return d.GetQuack()
}
