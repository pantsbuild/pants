// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.aliases;

/**
 * Part of an integration test to ensure that target aliases are replaced by their dependencies in
 * the build graph.
 *
 * See tests/python/pants_test/core_tasks/test_substitute_target_aliases_integration.py
 */
public class UseIntransitiveDependency {

  public static void main(String[] args) {
    System.out.println("Managed to run this class.");
  }

  /**
   * We don't attempt to reference this, because this will assuredly fail at run-time. We just want
   * to make sure this reference is here at compile-time.
   */
  public static void referenceIntransitive() {
    new IntransitiveDependency();
  }

}
