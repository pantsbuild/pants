// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.deployexcludes;

import com.google.common.base.Joiner;
import com.google.common.collect.ImmutableSortedSet;
import java.util.Set;

public class DeployExcludesMain {
  public static void main(String[] args) {
    Set values = ImmutableSortedSet.of("Hello", "World");
    System.out.println("DeployExcludes " + Joiner.on(" ").join(values));
  }
}

