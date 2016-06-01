// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.collect.ImmutableList;
import org.junit.Test;
import org.pantsbuild.tools.junit.lib.AnnotationOverrideClass;
import org.pantsbuild.tools.junit.lib.ParallelAnnotatedClass;
import org.pantsbuild.tools.junit.lib.UnannotatedTestClass;

import static org.junit.Assert.assertEquals;

public class SpecTest {

  @Test public void testAddMethod() throws Exception {
    Spec spec = new Spec(UnannotatedTestClass.class);
    assertEquals(UnannotatedTestClass.class, spec.getSpecClass());
    assertEquals("org.pantsbuild.tools.junit.lib.UnannotatedTestClass",
        spec.getSpecName());
    assertEquals(ImmutableList.of(), spec.getMethods());
    spec.addMethod("testMethod");
    assertEquals(ImmutableList.of("testMethod"), spec.getMethods());
    spec.addMethod("foo");
    assertEquals(ImmutableList.of("testMethod", "foo"), spec.getMethods());
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
