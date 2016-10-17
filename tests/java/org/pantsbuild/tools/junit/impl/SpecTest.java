// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Test;
import org.pantsbuild.tools.junit.lib.AnnotationOverrideClass;
import org.pantsbuild.tools.junit.lib.ParallelAnnotatedClass;
import org.pantsbuild.tools.junit.lib.UnannotatedTestClass;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.emptyCollectionOf;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThat;

public class SpecTest {

  @Test public void testAddMethod() throws Exception {
    Spec spec = new Spec(UnannotatedTestClass.class);
    assertEquals(UnannotatedTestClass.class, spec.getSpecClass());
    assertEquals("org.pantsbuild.tools.junit.lib.UnannotatedTestClass",
        spec.getSpecName());
    assertThat(spec.getMethods(), emptyCollectionOf(String.class));
    Spec specWithMethodAdded = spec.withMethod("testMethod");
    assertThat(specWithMethodAdded.getMethods(), contains("testMethod"));
    assertThat(specWithMethodAdded.withMethod("foo").getMethods(), contains("testMethod", "foo"));
  }

  @Test public void testDefaultConcurrency() {
    Spec spec = new Spec(UnannotatedTestClass.class);
    assertEquals(Concurrency.SERIAL, spec.getConcurrency(Concurrency.SERIAL));
    assertEquals(Concurrency.PARALLEL_CLASSES, spec.getConcurrency(Concurrency.PARALLEL_CLASSES));
    assertEquals(Concurrency.PARALLEL_METHODS, spec.getConcurrency(Concurrency.PARALLEL_METHODS));
    assertEquals(Concurrency.PARALLEL_CLASSES_AND_METHODS,
        spec.getConcurrency(Concurrency.PARALLEL_CLASSES_AND_METHODS));
  }

  @Test public void testAnnotatedConcurrency() {
    Spec spec = new Spec(ParallelAnnotatedClass.class);
    assertEquals(Concurrency.PARALLEL_CLASSES,
        spec.getConcurrency(Concurrency.PARALLEL_CLASSES_AND_METHODS));
    assertEquals(Concurrency.PARALLEL_CLASSES, spec.getConcurrency(Concurrency.PARALLEL_CLASSES));
    assertEquals(Concurrency.PARALLEL_CLASSES, spec.getConcurrency(Concurrency.PARALLEL_METHODS));
    assertEquals(Concurrency.PARALLEL_CLASSES, spec.getConcurrency(Concurrency.SERIAL));
  }

  @Test public void testAnnotationPrecedence() {
    Spec spec = new Spec(AnnotationOverrideClass.class);
    assertEquals(Concurrency.SERIAL, spec.getConcurrency(Concurrency.PARALLEL_CLASSES_AND_METHODS));
    assertEquals(Concurrency.SERIAL, spec.getConcurrency(Concurrency.PARALLEL_CLASSES));
    assertEquals(Concurrency.SERIAL, spec.getConcurrency(Concurrency.PARALLEL_METHODS));
    assertEquals(Concurrency.SERIAL, spec.getConcurrency(Concurrency.SERIAL));
  }
}
