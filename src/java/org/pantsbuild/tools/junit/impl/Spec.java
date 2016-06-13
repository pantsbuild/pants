// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Preconditions;
import com.google.common.collect.ImmutableList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Set;
import org.pantsbuild.junit.annotations.TestParallel;
import org.pantsbuild.junit.annotations.TestParallelClassesAndMethods;
import org.pantsbuild.junit.annotations.TestParallelMethods;
import org.pantsbuild.junit.annotations.TestSerial;

/**
 * Represents a parsed test spec from the junit-runner command line.
 */
class Spec {
  private final Class<?> clazz;
  private final Set<String> methods;

  public Spec(Class<?> clazz) {
    Preconditions.checkNotNull(clazz);
    this.clazz = clazz;
    this.methods = new LinkedHashSet<String>();
  }

  public String getSpecName() {
    return this.clazz.getName();
  }

  public Class<?> getSpecClass() {
    return this.clazz;
  }

  public void addMethod(String method) {
    Preconditions.checkNotNull(method);
    methods.add(method);
  }

  /**
   * @return either the Concurrency value specified by the class annotation or the default
   * concurrency setting passed in the parameter.
   */
  public Concurrency getConcurrency(Concurrency defaultConcurrency) {
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
    return ImmutableList.copyOf(methods);
  }
}
