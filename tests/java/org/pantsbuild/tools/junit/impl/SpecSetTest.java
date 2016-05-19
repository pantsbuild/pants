package org.pantsbuild.tools.junit.impl;

import com.google.common.collect.ImmutableList;
import java.util.Set;
import org.junit.Test;
import org.pantsbuild.tools.junit.impl.Concurrency;
import org.pantsbuild.tools.junit.impl.Spec;
import org.pantsbuild.tools.junit.impl.SpecSet;
import org.pantsbuild.tools.junit.lib.AnnotationOverrideClass;
import org.pantsbuild.tools.junit.lib.ParallelBothAnnotatedClass;
import org.pantsbuild.tools.junit.lib.UnannotatedTestClass;

import static org.junit.Assert.assertEquals;

/**
 * Created by zundel on 5/2/16.
 */
public class SpecSetTest {

  @Test public void testExtractClasses() {
    // Not annotated
    Spec dummyClassSpec = new Spec(UnannotatedTestClass.class);
    // Annotated with PARALLEL_SERIAL
    Spec annotationOverrideSpec = new Spec(AnnotationOverrideClass.class);
    // Annotated with PARALLEL_BOTH
    Spec parallelBothSpec = new Spec(ParallelBothAnnotatedClass.class);

    SpecSet specSet = new SpecSet(
        ImmutableList.of(dummyClassSpec, annotationOverrideSpec, parallelBothSpec),
        Concurrency.PARALLEL_CLASSES);

    assertEquals(3, specSet.specs().size());
    Class<?>[] parallelBothClasses = specSet.extract(Concurrency.PARALLEL_BOTH).classes();
    assertEquals(1, parallelBothClasses.length);
    assertEquals(ParallelBothAnnotatedClass.class, parallelBothClasses[0]);
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
