// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Test Hello World example's greet lib, which says "Hello" to things.

package com.pants.examples.hello.greet;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/* Ensure our greetings are polite */
public class GreetingTest {
  @Test
  public void mentionGreetee() {
    String greetingForFoo = Greeting.greet("Foo");
    assertEquals(true, greetingForFoo.contains("Foo"));
  }
  @Test
  public void shouldSayHello() {
    String greetingForFoo = Greeting.greet("Foo");
    assertEquals(true, greetingForFoo.contains("Hello"));
  }
}
