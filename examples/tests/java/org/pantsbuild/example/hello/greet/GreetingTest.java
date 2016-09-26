// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Test Hello World example's greet lib, which says "Hello" to things.

package org.pantsbuild.example.hello.greet;

import org.junit.Test;

import static org.hamcrest.CoreMatchers.containsString;
import static org.junit.Assert.assertThat;

/* Ensure our greetings are polite */
public class GreetingTest {
  @Test
  public void mentionGreetee() {
    String greetingForFoo = Greeting.greet("Foo");
    assertThat(greetingForFoo, containsString("Foo"));
  }

  @Test
  public void mentionGreeteeFromResource() throws Exception {
    String greeting = Greeting.greetFromResource("org/pantsbuild/example/hello/world.txt");
    assertThat(greeting, containsString("Resource World"));
  }

  @Test
  public void shouldSayHello() {
    String greetingForFoo = Greeting.greet("Foo");
    assertThat(greetingForFoo, containsString("Hello"));
  }
}
