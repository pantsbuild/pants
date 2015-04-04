namespace java com.pants.examples.hello.thriftjava

include com.pants.examples.person.Person;

struct HelloMessage {
  1: string salutation = "Hello";
  2: Person person;
}
