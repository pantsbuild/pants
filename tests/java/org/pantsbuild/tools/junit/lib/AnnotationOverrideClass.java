package org.pantsbuild.tools.junit.lib;

import org.pantsbuild.junit.annotations.TestParallel;
import org.pantsbuild.junit.annotations.TestParallelBoth;
import org.pantsbuild.junit.annotations.TestParallelMethods;
import org.pantsbuild.junit.annotations.TestSerial;

/**
 * Tests the annotation override behavior.
 * {@link TestSerial} should override all other annotations.
 */
@TestParallel
@TestSerial
@TestParallelMethods
@TestParallelBoth
public class AnnotationOverrideClass {
}
