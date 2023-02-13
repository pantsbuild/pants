package org.pantsbuild.args4j;

import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.OptionDef;
import org.kohsuke.args4j.spi.Messages;
import org.kohsuke.args4j.spi.OptionHandler;
import org.kohsuke.args4j.spi.Parameters;
import org.kohsuke.args4j.spi.Setter;

/** Picks up all non-option prefixed arguments. Can only be used with Argument types. */
public class StringArgumentsHandler extends OptionHandler<String> {

  public StringArgumentsHandler(CmdLineParser parser, OptionDef option, Setter<String> setter) {
    super(parser, option, setter);

    if (!option.isArgument()) {
      throw new IllegalArgumentException(
          StringArgumentsHandler.class.getSimpleName()
              + " must be used with an argument not an "
              + "option. Was used for option with usage: "
              + option.usage());
    }
  }

  @Override
  public int parseArguments(Parameters params) throws CmdLineException {
    int counter = 0;
    for (; counter < params.size(); counter++) {
      String param = params.getParameter(counter);

      if (param.startsWith("-")) {
        break;
      }

      setter.addValue(param);
    }

    return counter;
  }

  @Override
  public String getDefaultMetaVariable() {
    return Messages.DEFAULT_META_REST_OF_ARGUMENTS_HANDLER.format();
  }
}
