// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import java.util.List;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.Lists;

import org.junit.Test;
import org.kohsuke.args4j.Argument;
import org.kohsuke.args4j.Option;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class TestParser {
  public static class Options {
    @Option(name = "-v")
    boolean verbose;

    @Argument
    List<String> positional = Lists.newArrayList();
  }

  private Options parse(boolean expectSuccess, String... args) {
    Options options = new Options();
    Parser.Result result = Parser.parse(options, args);
    assertEquals(expectSuccess, !result.isFailure());
    return options;
  }

  private Options parseSuccess(String... args) {
    return parse(true, args);
  }

  private Options parseFailure(String... args) {
    return parse(false, args);
  }

  @Test
  public void testFailure() {
    parseFailure("-not-an-option");
  }

  @Test
  public void testSuccess() {
    Options options = parseSuccess("-v");
    assertTrue(options.verbose);
  }

  @Test
  public void testPositionalFirst() {
    Options options = parseSuccess("one", "two", "three", "-v");
    assertEquals(ImmutableList.of("one", "two", "three"), ImmutableList.copyOf(options.positional));
  }

  @Test
  public void testPositionalLast() {
    Options options = parseSuccess("-v", "one", "two", "three");
    assertEquals(ImmutableList.of("one", "two", "three"), ImmutableList.copyOf(options.positional));
  }

  @Test
  public void testPositionalOnly() {
    Options options = parseSuccess("one", "two", "three");
    assertEquals(ImmutableList.of("one", "two", "three"), ImmutableList.copyOf(options.positional));
  }
}
