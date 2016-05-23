// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.collect.ImmutableList;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;
import org.pantsbuild.tools.junit.lib.MockJUnit3Test;
import org.pantsbuild.tools.junit.lib.MockRunWithTest;
import org.pantsbuild.tools.junit.lib.UnannotatedTestClass;

import static org.hamcrest.CoreMatchers.containsString;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThat;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class SpecParserTest {
  private static final String DUMMY_CLASS_NAME =
      "org.pantsbuild.tools.junit.lib.UnannotatedTestClass";
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

  private void assertNoSpecs(String className) throws Exception {
    String specString = "org.pantsbuild.tools.junit.lib." + className;
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    List<Spec> specs = parser.parse();
    assertTrue(specs.isEmpty());
  }

  /**
   * These are all classes/interfaces, but aren't test classes. Pants will pass in all the classes
   * and interfaces it finds, but if they get passed down to the BlockJUnit4Runner, the runner
   * will throw an InitializationError
   *
   * @throws Exception
   */
  @Test public void testNotATest() throws Exception {
    assertNoSpecs("NotATestAbstractClass");
    assertNoSpecs("NotATestInterface");
    assertNoSpecs("NotATestNonzeroArgConstructor");
    assertNoSpecs("NotATestNoPublicConstructor");
    assertNoSpecs("NotATestNoRunnableMethods");
    assertNoSpecs("NotATestPrivateClass");
  }

  @Test public void testJUnit3() throws Exception {
    String specString = "org.pantsbuild.tools.junit.lib.MockJUnit3Test";
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    List<Spec> specs = parser.parse();
    assertEquals(1, specs.size());
    assertEquals(MockJUnit3Test.class, specs.get(0).getSpecClass());
  }

  @Test public void testRunWith() throws Exception {
    String specString = "org.pantsbuild.tools.junit.lib.MockRunWithTest";
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    List<Spec> specs = parser.parse();
    assertEquals(1, specs.size());
    assertEquals(MockRunWithTest.class, specs.get(0).getSpecClass());
  }
}
