// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.pantsbuild.junit.annotations.TestParallel;
import org.pantsbuild.junit.annotations.TestParallelClassesAndMethods;
import org.pantsbuild.junit.annotations.TestParallelMethods;
import org.pantsbuild.junit.annotations.TestSerial;

/**
 * Tests the annotation override behavior.
 * {@link TestSerial} should override all other annotations.
 */
@TestParallel
@TestSerial
@TestParallelMethods
@TestParallelClassesAndMethods
public class AnnotationOverrideClass {
}
