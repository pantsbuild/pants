// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import com.google.common.base.Charsets;
import com.google.common.io.Files;
import java.io.File;
import java.io.IOException;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.spi.OptionHandler;
import org.kohsuke.args4j.spi.Parameters;

/**
 * An {@code OptionHandler} that can read an option value from an "argfile". An argfile is just a
 * file containing an option's value as its contents. These can be useful to avoid command-line
 * argument length limits. An argfile is specified on the command-line by prefixing the option
 * argument value with a {@code @}, like so:
 *
 * <pre>-potentially-long-argument=@/path/to/argfile</pre>
 *
 * The path can be relative in which case it is taken as relative to the working directory of the
 * associated java invocation.
 *
 * @param <T> The type of the underlying option value.
 */
public abstract class ArgfileOptionHandler<T> extends OptionHandler<T> {
  private final OptionHandler<T> delegate;

  /** @param delegate The {@code OptionHandler} to delegate final value parsing to. */
  protected ArgfileOptionHandler(OptionHandler<T> delegate) {
    super(delegate.owner, delegate.option, delegate.setter);
    this.delegate = delegate;
  }

  @Override
  public int parseArguments(final Parameters params) throws CmdLineException {
    return delegate.parseArguments(
        new Parameters() {
          @Override
          public String getParameter(int idx) throws CmdLineException {
            String value = params.getParameter(idx);
            if (!value.startsWith("@")) {
              return value;
            }

            try {
              return Files.toString(new File(value.substring(1)), Charsets.UTF_8).trim();
            } catch (IOException e) {
              throw new InvalidCmdLineArgumentException(
                  delegate.option,
                  value,
                  String.format("Failed to read argfile: %s", e.getMessage()));
            }
          }

          @Override
          public int size() {
            return params.size();
          }
        });
  }

  @Override
  public String getDefaultMetaVariable() {
    return delegate.getDefaultMetaVariable();
  }
}
