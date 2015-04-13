// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import org.junit.Test;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class BooleanOptionHandlerTest {
  public static class Options {
    @Option(name = "-q", metaVar = "QUIET", handler = BooleanOptionHandler.class)
    boolean quiet;
  }

  private Options parse(String... args) throws CmdLineException {
    Options options = new Options();
    CmdLineParser cmdLineParser = new CmdLineParser(options);
    cmdLineParser.parseArgument(args);
    return options;
  }

  @Test
  public void testNoArg() throws CmdLineException {
    assertTrue(parse("-q").quiet);
  }

  @Test
  public void testArg() throws CmdLineException {
    // Only case-variants of 'true' are true.
    assertTrue(parse("-q", "true").quiet);
    assertTrue(parse("-q", "True").quiet);
    assertTrue(parse("-q", "TRUE").quiet);

    assertFalse(parse("-q", "false").quiet);
    assertFalse(parse("-q", "yes").quiet);
    assertFalse(parse("-q", "no").quiet);
    assertFalse(parse("-q", "jake").quiet);
    assertFalse(parse("-q", "0").quiet);
    assertFalse(parse("-q", "1").quiet);
  }
}