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
  private final boolean hasCustomRunner;

  Spec(Class<?> clazz) {
    this(clazz, ImmutableSet.of());
  }

  private Spec(Class<?> clazz, ImmutableSet<String> methods) {
    this(clazz, methods, false);
  }

  private Spec(Class<?> clazz, ImmutableSet<String> methods, boolean hasCustomRunner) {
    this.clazz = Objects.requireNonNull(clazz);
    this.methods = Objects.requireNonNull(methods);
    this.hasCustomRunner = hasCustomRunner;
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
    return new Spec(clazz, ImmutableSet.<String>builder().addAll(methods).add(method).build(),
        this.hasCustomRunner);
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

  // NB: If a test class has a custom runner, then we can't assume spec's method portion's format.
  public Spec asCustomRunnerSpec() {
    return new Spec(this.clazz, this.methods, true);
  }

  public boolean methodNameAllowedToNotMatch() {
    return hasCustomRunner;
  }

  @Override
  public String toString() {
    return "Spec{" +
        "clazz=" + clazz +
        ", methods=" + methods +
        ", hasCustomRunner=" + hasCustomRunner +
        '}';
  }
}
