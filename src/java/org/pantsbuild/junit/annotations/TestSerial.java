// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.junit.annotations;

import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Annotate that a test class must be run in serial. See usage note in
 * {@code org.pantsbuild.tools.junit.impl.ConsoleRunnerImpl}. This annotation takes precedence
 * over a {@link TestParallel} annotation if a class has both (including via inheritance).
 * <P>
 * Note that this annotation is not currently compatible with the PARALLEL_METHODS or
 * PARALLEL_CLASSES_AND_METHODS default concurrency setting. See
 * <a href="https://github.com/pantsbuild/pants/issues/3209">issue 3209</a>
 */
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@Target(ElementType.TYPE)
public @interface TestSerial {
}
