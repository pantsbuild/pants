// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import java.util.List;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.Lists;
import com.google.common.primitives.Booleans;

import org.junit.Test;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;
import org.kohsuke.args4j.OptionDef;
import org.kohsuke.args4j.spi.Setter;

import static org.junit.Assert.assertEquals;

public class CollectionOptionHandlerTest {
  public static class BooleansOptionHandler extends CollectionOptionHandler<Boolean> {
    public BooleansOptionHandler(
        CmdLineParser parser,
        OptionDef option,
        Setter<? super Boolean> setter) {

      super(parser, option, setter, "BOOLEAN", new ItemParser<Boolean>() {
        @Override public Boolean parse(String item) {
          return Boolean.parseBoolean(item);
        }
      });
    }
  }

  public static class Options {
    @Option(name = "-b", metaVar = "BITS", handler = BooleansOptionHandler.class)
    List<Boolean> bits = Lists.newArrayList();
  }

  private Options parse(String... args) throws CmdLineException {
    Options options = new Options();
    CmdLineParser cmdLineParser = new CmdLineParser(options);
    cmdLineParser.parseArgument(args);
    return options;
  }

  private void assertParseEquals(String optionValue, boolean... expected) throws CmdLineException {
    Options options = parse("-b", optionValue);
    assertEquals(
        ImmutableList.copyOf(Booleans.asList(expected)),
        ImmutableList.copyOf(options.bits));
  }

  @Test
  public void testSingle() throws CmdLineException {
    assertParseEquals("true", true);
    assertParseEquals("false", false);
    assertParseEquals("true,", true);
    assertParseEquals("false,", false);

    // TODO(John Sirois): This syntax should probably result in a InvalidCmdLineArgumentException
    // but currently CollectionOptionHandler leverages DelimitedOptionHandler and we have no control
    // over parsing.  Consider ditching the base class and just parsing ourselves.
    // See: https://github.com/pantsbuild/pants/issues/1418
    assertParseEquals(",");
  }

  @Test
  public void testMultiple() throws CmdLineException {
    assertParseEquals("true,false", true, false);
    assertParseEquals("true,false,", true, false);
    assertParseEquals("true,false,true", true, false, true);

    // TODO(John Sirois): This syntax should probably result in a InvalidCmdLineArgumentException
    // but currently CollectionOptionHandler leverages DelimitedOptionHandler and we have no control
    // over parsing.  Consider ditching the base class and just parsing ourselves.
    // See: https://github.com/pantsbuild/pants/issues/1418

    assertParseEquals(",false,true", false, false, true);
  }
}
