// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.junit.annotations;

import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Annotate that methods in this test class can be run in parallel and it can run in parallel with
 * other test classes. See usage note in
 * {@code org.pantsbuild.tools.junit.impl.ConsoleRunnerImpl}. The {@link TestSerial}
 * {@link TestParallel} {@link TestParallelMethods} annotations takes precedence over this
 * annotation if a class has multiple annotations (including via inheritance).
 * <p>
 * Requires use of the experimental test runner.
 */
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@Target(ElementType.TYPE)
public @interface TestParallelClassesAndMethods {
}