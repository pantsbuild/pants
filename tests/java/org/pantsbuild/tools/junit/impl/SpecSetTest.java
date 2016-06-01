// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.collect.ImmutableList;
import java.util.Set;
import org.junit.Test;
import org.pantsbuild.tools.junit.lib.AnnotationOverrideClass;
import org.pantsbuild.tools.junit.lib.ParallelClassesAndMethodsAnnotatedClass;
import org.pantsbuild.tools.junit.lib.UnannotatedTestClass;

import static org.junit.Assert.assertEquals;

public class SpecSetTest {

  @Test public void testExtractClasses() {
    Spec dummyClassSpec = new Spec(UnannotatedTestClass.class);
    Spec annotationOverrideSpec = new Spec(AnnotationOverrideClass.class);
    Spec parallelBothSpec = new Spec(ParallelClassesAndMethodsAnnotatedClass.class);

    SpecSet specSet = new SpecSet(
        ImmutableList.of(dummyClassSpec, annotationOverrideSpec, parallelBothSpec),
        Concurrency.PARALLEL_CLASSES);

    assertEquals(3, specSet.specs().size());
    Class<?>[] parallelBothClasses =
        specSet.extract(Concurrency.PARALLEL_CLASSES_AND_METHODS).classes();
    assertEquals(1, parallelBothClasses.length);
    assertEquals(ParallelClassesAndMethodsAnnotatedClass.class, parallelBothClasses[0]);
    assertEquals(2, specSet.specs().size());

    assertEquals(0, specSet.extract(Concurrency.PARALLEL_METHODS).specs().size());
    assertEquals(2, specSet.specs().size());

    Class<?>[] parallelClassClasses = specSet.extract(Concurrency.PARALLEL_CLASSES).classes();
    assertEquals(1, parallelClassClasses.length);
    assertEquals(UnannotatedTestClass.class, parallelClassClasses[0]);

    Set<Spec> remaining = specSet.specs();
    assertEquals(1, remaining.size());
    Spec remainingSpec = remaining.iterator().next();
    assertEquals(AnnotationOverrideClass.class, remainingSpec.getSpecClass());
  }
}
