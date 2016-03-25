package usethrift

import "thrifttest/duck"

type EchoServerImpl struct {
	//nothing
}

func (s EchoServerImpl) Ping() (err error) {
	return nil
}

func (s EchoServerImpl) Echo(input string) (r string, err error) {
	return input, nil
}

func whatevs() string {
	d := duck.NewDuck()
	s := &EchoServerImpl{}
	p := duck.NewEchoServerProcessor(s)
	_, ok := p.GetProcessorFunction("ping")
	if !ok {
		panic("no ping func")
	}
	return d.GetQuack()
}
