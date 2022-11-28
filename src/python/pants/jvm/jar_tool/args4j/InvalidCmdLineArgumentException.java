// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import javax.annotation.Nullable;
import org.kohsuke.args4j.OptionDef;

/**
 * Indicates a problem parsing a command line argument.
 *
 * <p>Although args4j provides {@link org.kohsuke.args4j.CmdLineException} it is difficult to
 * construct one. As such, this exception is useful for implementing {@link
 * org.kohsuke.args4j.spi.OptionHandler OptionHandlers} that detect and reject malformed values.
 */
public class InvalidCmdLineArgumentException extends RuntimeException {

  /**
   * @param optionDef The {@code OptionDef} describing the option being parsed.
   * @param optionValue The raw value of the option being parsed.
   * @param message A message describing how the {@code optionValue} is invalid.
   */
  public InvalidCmdLineArgumentException(
      OptionDef optionDef, @Nullable Object optionValue, String message) {

    super(
        String.format(
            "Invalid option value '%s' for the option with usage '%s': %s",
            optionValue, optionDef.usage(), message));
  }

  /**
   * @param optionName The name of the option being parsed.
   * @param optionValue The raw value of the option being parsed.
   * @param message A message describing how the {@code optionValue} is invalid.
   */
  public InvalidCmdLineArgumentException(
      String optionName, @Nullable Object optionValue, String message) {

    super(
        String.format(
            "Invalid option value '%s' for option '%s': %s", optionValue, optionName, message));
  }
}
