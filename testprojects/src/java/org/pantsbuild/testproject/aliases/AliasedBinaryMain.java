// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.aliases;

/**
 * Part of an integration test to ensure that jvm_binaries referenced indirectly through an alias()
 * in a BUILD file can still be executed with ./pants run.
 *
 * See tests/python/pants_test/core_tasks/test_substitute_target_aliases_integration.py
 */
public class AliasedBinaryMain {

  public static void main(String[] args) {
    // NB: This message is checked for in an integration test.
    System.out.println(AliasedBinaryMain.class.getSimpleName() + " is up and running.");
  }

}