// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import java.io.File;
import java.io.IOException;

import com.google.common.base.Charsets;
import com.google.common.io.Files;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;
import org.kohsuke.args4j.OptionDef;
import org.kohsuke.args4j.spi.Setter;
import org.kohsuke.args4j.spi.StringOptionHandler;

import static org.junit.Assert.assertEquals;

public abstract class ArgfileOptionHandlerTest {
  public static class TestArgFileHandler extends ArgfileOptionHandler<String> {
    public TestArgFileHandler(
        CmdLineParser parser,
        OptionDef option,
        Setter<? super String> setter) {
      super(new StringOptionHandler(parser, option, setter));
    }
  }

  public static class Options {
    @Option(name="-m", metaVar = "MESSAGE", handler = TestArgFileHandler.class)
    String message;
  }

  protected Options parse(String... args) throws CmdLineException {
    Options options = new Options();
    CmdLineParser cmdLineParser = new CmdLineParser(options);
    cmdLineParser.parseArgument(args);
    return options;
  }

  public static class TestNoArgfile extends ArgfileOptionHandlerTest {
    @Test
    public void testNoArgfile() throws CmdLineException {
      Options options = parse("-m", "bob");
      assertEquals("bob", options.message);
    }
  }

  public static class TestArgile extends ArgfileOptionHandlerTest {
    @Rule
    public TemporaryFolder temporary = new TemporaryFolder();

    @Test
    public void testArgfile() throws CmdLineException, IOException {
      File argfile = temporary.newFile("argfile");
      Files.write("bill", argfile, Charsets.UTF_8);
      Options options = parse("-m", String.format("@%s", argfile.getPath()));
      assertEquals("bill", options.message);
    }
  }
}
