// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Test the cucumber library which contains unicode classnames

package org.pantsbuild.testproject.unicode.cucumber;

import org.junit.Test;

import org.pantsbuild.testproject.unicode.cucumber.CucumberAnnotatedExample;

import static org.junit.Assert.assertEquals;

/** Ensure our greetings are polite */
public class CucumberTest {
  @Test
  public void testUnicodeClass() {
    assertEquals("Have a nice day!", new CucumberAnnotatedExample().pleasantry());
  }
}
