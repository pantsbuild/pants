// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.junit.annotations;

import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Annotate that methods in this test class can be run in parallel. Note that this will not run in
 * parallel with other classes. If you want that behavior too, specify
 * {@link TestParallelClassesAndMethods}.  See usage note in
 * {@code org.pantsbuild.tools.junit.impl.ConsoleRunnerImpl}. The
 * {@link TestSerial} and {@link TestParallel} annotation takes precedence over this annotation
 * if a class has multiple annotations (including via inheritance).
 * <p>
 * Requires use of the experimental test runner.
 */
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@Target(ElementType.TYPE)
public @interface TestParallelMethods {
}