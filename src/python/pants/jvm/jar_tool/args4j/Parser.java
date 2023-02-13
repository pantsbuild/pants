// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import com.google.common.base.Optional;
import com.google.common.collect.Lists;
import java.io.OutputStream;
import java.io.PrintStream;
import java.util.Iterator;
import java.util.List;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.OptionHandlerRegistry;
import org.kohsuke.args4j.ParserProperties;

/**
 * Encapsulates args4j command line parsing and makes it behave similar to com.twitter.common.args.
 */
public class Parser {

  /** Represents the result of a command line argument parse. */
  public static final class Result {
    static Result failure(CmdLineParser parser, String message, Object... parameters) {
      return new Result(parser, Optional.of(String.format(message, parameters)));
    }

    static Result success(CmdLineParser cmdLineParser) {
      return new Result(cmdLineParser, Optional.<String>absent());
    }

    private final CmdLineParser parser;
    private final Optional<String> failure;

    private Result(CmdLineParser parser, Optional<String> failure) {
      this.parser = parser;
      this.failure = failure;
    }

    /** @return {@code true} if the command line parse failed. */
    public boolean isFailure() {
      return failure.isPresent();
    }

    /**
     * Prints command line usage.
     *
     * <p>The usage will include failure details if the command line parse was a failure according
     * to {@link #isFailure()}.
     *
     * @param out The stream to print command line usage to.
     */
    public void printUsage(OutputStream out) {
      PrintStream helpPrinter = new PrintStream(out);
      if (failure.isPresent()) {
        helpPrinter.println(failure.get());
        helpPrinter.println();
      }

      helpPrinter.println("Usage:");
      parser.printSingleLineUsage(helpPrinter);
      helpPrinter.println(); // printSingleLineUsage does not include a newline

      helpPrinter.println();
      parser.printUsage(helpPrinter);
    }
  }

  /**
   * Parses command line arguments and populates the given {@code option} bean with the values if
   * the parse is successful.
   *
   * @param options The options bean to populate with the parsed command line options.
   * @param args The command line arguments to parse.
   * @return The result of the parse.
   */
  public static Result parse(Object options, String... args) {
    OptionHandlerRegistry.getRegistry().registerHandler(boolean.class, BooleanOptionHandler.class);
    OptionHandlerRegistry.getRegistry().registerHandler(Boolean.class, BooleanOptionHandler.class);

    ParserProperties parserProperties =
        ParserProperties.defaults()
            // The @ syntax here is global, @argfile alone is a file one or more options in it.
            // The jar-tool traditionally accepted limited @argfile switch values, ie: -f=@argfile,
            // and the contents of the argfile was the single option's value.
            // As such we turn off args4j @ syntax explicitly and implement a custom OptionHandler
            // to retain the traditional jar-tool @ semantics.
            .withAtSyntax(false)
            .withOptionValueDelimiter("=")
            .withShowDefaults(true);

    // Args4j expects positional arguments come 1st whereas pants traditionally expects them to come
    // last.  Fixup the order to suit Args4j if needed.
    // NB: This only works because we set the option value delimiter to non-whitespace above!
    List<String> arguments = Lists.newArrayList(args);
    if (arguments.size() > 1) {
      List<String> positionalArgs = Lists.newArrayList();
      Iterator<String> reverseArgIterator = Lists.reverse(arguments).iterator();
      while (reverseArgIterator.hasNext()) {
        String arg = reverseArgIterator.next();
        if (!arg.startsWith("-")) {
          reverseArgIterator.remove();
          positionalArgs.add(arg);
        } else {
          break;
        }
      }
      arguments.addAll(0, Lists.reverse(positionalArgs));
    }

    CmdLineParser cmdLineParser = new CmdLineParser(options, parserProperties);
    try {
      cmdLineParser.parseArgument(arguments);
      return Result.success(cmdLineParser);
    } catch (CmdLineException e) {
      return Result.failure(cmdLineParser, "Invalid command line:\n\t%s", e.getLocalizedMessage());
    } catch (InvalidCmdLineArgumentException e) {
      return Result.failure(cmdLineParser, "Invalid command line parameter:\n\t%s", e.getMessage());
    } finally {
      // Unregister our custom CmdLineParser handlers because the OptionHandlerRegistry
      // is a global singleton and we don't want to affect other users of CmdLineParser.
      // This is most common when multiple tests are run at the same time.
      OptionHandlerRegistry.getRegistry()
          .registerHandler(boolean.class, org.kohsuke.args4j.spi.BooleanOptionHandler.class);
      OptionHandlerRegistry.getRegistry()
          .registerHandler(Boolean.class, org.kohsuke.args4j.spi.BooleanOptionHandler.class);
    }
  }
}
