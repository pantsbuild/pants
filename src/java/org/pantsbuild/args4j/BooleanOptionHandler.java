// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.OptionDef;
import org.kohsuke.args4j.spi.OptionHandler;
import org.kohsuke.args4j.spi.Parameters;
import org.kohsuke.args4j.spi.Setter;

/**
 * An {@code OptionHandler} that parses boolean values but can also set them from presence alone.
 *
 * <p>The {@link org.kohsuke.args4j.spi.BooleanOptionHandler built-in args4j boolean parser} takes
 * one argument which is parsed to a {@code boolean} option value. This handler can similarly take a
 * value; although, the value is parsed as per {@link Boolean#parseBoolean(String)}. In addition
 * this handler will treat no value as {@code true}. For example, the following all parse to {@code
 * true}:
 *
 * <ul>
 *   <li>{@code -verbose}
 *   <li>{@code -verbose=true}
 *   <li>{@code -verbose=TRUE}
 * </ul>
 *
 * And the following all parse to {@code false}:
 *
 * <ul>
 *   <li>{@code -verbose=false}
 *   <li>{@code -verbose=FALSE}
 * </ul>
 *
 * Be careful! These are false (as per {@link Boolean#parseBoolean(String)}) too:
 *
 * <ul>
 *   <li>{@code -verbose=no}
 *   <li>{@code -verbose=yes}
 *   <li>{@code -verbose=0}
 *   <li>{@code -verbose=1}
 * </ul>
 */
public class BooleanOptionHandler extends OptionHandler<Boolean> {

  public BooleanOptionHandler(
      CmdLineParser parser, OptionDef option, Setter<? super Boolean> setter) {
    super(parser, option, setter);
  }

  @Override
  public int parseArguments(Parameters params) throws CmdLineException {
    if (params.size() == 0) {
      setter.addValue(true);
      return 0;
    } else {
      setter.addValue(Boolean.parseBoolean(params.getParameter(0)));
      return 1;
    }
  }

  @Override
  public String getDefaultMetaVariable() {
    return "BOOL";
  }
}
