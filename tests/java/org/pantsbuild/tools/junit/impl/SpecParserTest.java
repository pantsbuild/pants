// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.ArrayList;
import java.util.Collection;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.Iterables;

import org.junit.Test;
import org.pantsbuild.tools.junit.lib.MockJUnit3Test;
import org.pantsbuild.tools.junit.lib.MockRunWithTest;
import org.pantsbuild.tools.junit.lib.MockScalaTest;
import org.pantsbuild.tools.junit.lib.UnannotatedTestClass;

import static org.hamcrest.CoreMatchers.containsString;
import static org.hamcrest.Matchers.contains;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThat;
import static org.junit.Assert.assertTrue;

public class SpecParserTest {
  private static final String DUMMY_CLASS_NAME =
      "org.pantsbuild.tools.junit.lib.UnannotatedTestClass";
  private static final String DUMMY_METHOD_NAME = "testMethod";

  @Test(expected = IllegalArgumentException.class)
  public void testEmptySpecsThrows() {
    new SpecParser(new ArrayList<String>());
  }

  @Test public void testParserClass() throws Exception {
    SpecParser parser = new SpecParser(ImmutableList.of(DUMMY_CLASS_NAME));
    Collection<Spec> specs = parser.parse();
    Spec spec = Iterables.getOnlyElement(specs);
    assertEquals(UnannotatedTestClass.class,spec.getSpecClass());
    assertEquals(DUMMY_CLASS_NAME, spec.getSpecName());
    assertEquals(0, spec.getMethods().size());
  }

  @Test public void testParserMethod() throws Exception {
    String specString = DUMMY_CLASS_NAME + "#" + DUMMY_METHOD_NAME;
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    Collection<Spec> specs = parser.parse();
    Spec spec = Iterables.getOnlyElement(specs);
    assertEquals(UnannotatedTestClass.class, spec.getSpecClass());
    assertEquals(DUMMY_CLASS_NAME, spec.getSpecName());
    assertThat(spec.getMethods(), contains(DUMMY_METHOD_NAME));
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
    Collection<Spec> specs = parser.parse();
    assertTrue(specs.isEmpty());
  }

  /**
   * These are all classes/interfaces, but aren't test classes. Pants will pass in all the classes
   * and interfaces it finds, but if they get passed down to the BlockJUnit4Runner, the runner
   * will throw an InitializationError
   */
  @Test public void testNotATestClassSpec() throws Exception {
    assertNoSpecs("NotATestAbstractClass");
    assertNoSpecs("NotATestInterface");
    assertNoSpecs("NotATestNonzeroArgConstructor");
    assertNoSpecs("NotATestNoPublicConstructor");
    assertNoSpecs("NotATestNoRunnableMethods");
    assertNoSpecs("NotATestPrivateClass");
  }

  @Test public void testNotATestMethodSpec() throws Exception {
    String specString = "org.pantsbuild.tools.junit.lib.NotATestInterface#natif1";
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    Collection<Spec> specs = parser.parse();
    assertTrue(specs.isEmpty());
  }

  @Test public void testJUnit3() throws Exception {
    String specString = "org.pantsbuild.tools.junit.lib.MockJUnit3Test";
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    Collection<Spec> specs = parser.parse();
    Spec spec = Iterables.getOnlyElement(specs);
    assertEquals(MockJUnit3Test.class, spec.getSpecClass());
  }

  @Test public void testRunWith() throws Exception {
    String specString = "org.pantsbuild.tools.junit.lib.MockRunWithTest";
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    Collection<Spec> specs = parser.parse();
    Spec spec = Iterables.getOnlyElement(specs);
    assertEquals(MockRunWithTest.class, spec.getSpecClass());
  }

  @Test public void testScalaTest() throws Exception {
    String specString = "org.pantsbuild.tools.junit.lib.MockScalaTest";
    SpecParser parser = new SpecParser(ImmutableList.of(specString));
    Collection<Spec> specs = parser.parse();
    Spec spec = Iterables.getOnlyElement(specs);
    assertEquals(MockScalaTest.class, spec.getSpecClass());
  }
}
