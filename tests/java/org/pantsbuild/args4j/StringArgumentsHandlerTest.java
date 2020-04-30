package org.pantsbuild.args4j;

import org.junit.Test;
import org.kohsuke.args4j.Argument;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.NamedOptionDef;
import org.kohsuke.args4j.Option;
import org.kohsuke.args4j.spi.ConfigElement;
import org.kohsuke.args4j.spi.OptionImpl;
import org.kohsuke.args4j.spi.StringOptionHandler;

import static org.hamcrest.CoreMatchers.is;
import static org.hamcrest.MatcherAssert.assertThat;

public class StringArgumentsHandlerTest {
  public static class Options {
    @Argument(metaVar = "REST", handler = StringArgumentsHandler.class)
    String[] rest;

    @Option(name="-m", metaVar = "MESSAGE", handler = StringOptionHandler.class)
    String message;
  }

  private Options parse(String... args) throws CmdLineException {
    Options options = new Options();
    CmdLineParser cmdLineParser = new CmdLineParser(options);
    cmdLineParser.parseArgument(args);
    return options;
  }

  @Test
  public void parsingArgumentsAndSkippingOptions() throws CmdLineException {
    assertThat(parse("a", "b c").rest, is(new String[]{"a", "b c"}));
    assertThat(parse("a", "-m", "msg", "b c").rest, is(new String[]{"a", "b c"}));
  }

  @Test(expected = IllegalArgumentException.class)
  public void errorOnOptionOption() throws ClassNotFoundException {
    ConfigElement ce = new ConfigElement();
    ce.name = "-a";

    new StringArgumentsHandler(null, new NamedOptionDef(new OptionImpl(ce)),null);
  }
}
