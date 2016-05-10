// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.collect.ImmutableList;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

import static org.hamcrest.CoreMatchers.containsString;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThat;
import static org.junit.Assert.fail;

public class SpecParserTest {
  private static final String DUMMY_CLASS_NAME =
      "org.pantsbuild.tools.junit.impl.UnannotatedTestClass";
  private static final String DUMMY_METHOD_NAME = "testMethod";

  @Test public void testEmptySpecsThrows() {
    try {
      SpecParser parser = new SpecParser(new ArrayList<String>());
      fail("Expected Exception");
    } catch (Throwable expected) {
    }
  }

  @Test public void testParserClass() throws Exception {
    SpecParser parser = new SpecParser(ImmutableList.of(DUMMY_CLASS_NAME));
    List<Spec> specs = parser.parse();
    assertEquals(1, specs.size());
    Spec spec = specs.get(0);
    assertEquals(UnannotatedTestClass.class,spec.getSpecClass());
    assertEquals(DUMMY_CLASS_NAME, spec.getSpecName());
    assertEquals(0, spec.getMethods().size());
  }

  @Test public void testParserMethod() throws Exception {
    String specString = DUMMY_CLASS_NAME + "#" + DUMMY_METHOD_NAME;
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    List<Spec> specs = parser.parse();
    assertEquals(1, specs.size());
    Spec spec = specs.get(0);
    assertEquals(UnannotatedTestClass.class, spec.getSpecClass());
    assertEquals(DUMMY_CLASS_NAME, spec.getSpecName());
    assertEquals(ImmutableList.of(DUMMY_METHOD_NAME), spec.getMethods());
  }

  @Test public void testMethodDupsClass() throws Exception {
    String specString = DUMMY_CLASS_NAME + "#" + DUMMY_METHOD_NAME;
    SpecParser parser = new SpecParser(ImmutableList.of(DUMMY_CLASS_NAME, specString));
    try {
      parser.parse();
    } catch (SpecException expected) {
      assertThat(expected.getMessage(),
          containsString("Request for entire class already requesting individual methods"));
    }
  }

  @Test public void testBadSpec() {
    String specString = DUMMY_CLASS_NAME + "#" + DUMMY_METHOD_NAME + "#" + "foo";
    SpecParser parser = new SpecParser(ImmutableList.of(DUMMY_CLASS_NAME, specString));
    try {
      parser.parse();
    } catch (SpecException expected) {
      assertThat(expected.getMessage(),
          containsString("Expected only one # in spec"));
    }
  }

  @Test public void testMissingClass() {
    String specString = "org.foo.bar.Baz" ;
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    try {
      parser.parse();
    } catch (SpecException expected) {
      assertThat(expected.getMessage(),
          containsString("Class org.foo.bar.Baz not found"));
    }
  }

  @Test public void testMissingMethod() {
    String specString = DUMMY_CLASS_NAME + "#doesNotExist";
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    try {
      parser.parse();
    } catch (SpecException expected) {
      assertThat(expected.getMessage(),
          containsString("Method doesNotExist not found in class"));
    }
  }

}
