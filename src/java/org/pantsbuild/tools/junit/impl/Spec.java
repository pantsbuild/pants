// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.Collection;
import java.util.Objects;

import com.google.common.collect.ImmutableSet;

import org.pantsbuild.junit.annotations.TestParallel;
import org.pantsbuild.junit.annotations.TestParallelClassesAndMethods;
import org.pantsbuild.junit.annotations.TestParallelMethods;
import org.pantsbuild.junit.annotations.TestSerial;

/**
 * Represents a parsed test spec from the junit-runner command line.
 */
class Spec {
  private final Class<?> clazz;
  private final ImmutableSet<String> methods;
  private static final ImmutableSet<String> empty = ImmutableSet.of();  // To get around java7 quirk

  Spec(Class<?> clazz) {
    this(clazz, Spec.empty);
  }

  private Spec(Class<?> clazz, ImmutableSet<String> methods) {
    this.clazz = Objects.requireNonNull(clazz);
    this.methods = Objects.requireNonNull(methods);
  }

  String getSpecName() {
    return this.clazz.getName();
  }

  Class<?> getSpecClass() {
    return this.clazz;
  }

  /**
   * Return a copy of this class spec, but with an additional method.
   *
   * @param method The method to add to the class spec.
   * @return A new spec that includes the added method.
   */
  Spec withMethod(String method) {
    return new Spec(clazz, ImmutableSet.<String>builder().addAll(methods).add(method).build());
  }

  /**
   * @return either the Concurrency value specified by the class annotation or the default
   * concurrency setting passed in the parameter.
   */
  Concurrency getConcurrency(Concurrency defaultConcurrency) {
    if (clazz.isAnnotationPresent(TestSerial.class)) {
      return Concurrency.SERIAL;
    } else if (clazz.isAnnotationPresent(TestParallel.class)) {
      return Concurrency.PARALLEL_CLASSES;
    } else if (clazz.isAnnotationPresent(TestParallelMethods.class)) {
      return Concurrency.PARALLEL_METHODS;
    } else if (clazz.isAnnotationPresent(TestParallelClassesAndMethods.class)) {
      return Concurrency.PARALLEL_CLASSES_AND_METHODS;
    }
    return defaultConcurrency;
  }

  public Collection<String> getMethods() {
    return methods;
  }
}
