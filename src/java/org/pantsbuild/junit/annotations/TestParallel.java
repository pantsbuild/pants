// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.junit.annotations;

import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Annotate that a test class can be run in parallel. See usage note in
 * {@code org.pantsbuild.tools.junit.impl.ConsoleRunnerImpl}. The {@link TestSerial} annotation
 * takes precedence over this annotation if a class has both (including via inheritance).
 */
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@Target(ElementType.TYPE)
public @interface TestParallel {
}
