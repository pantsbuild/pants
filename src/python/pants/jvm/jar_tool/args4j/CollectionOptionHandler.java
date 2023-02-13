// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.args4j;

import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.OptionDef;
import org.kohsuke.args4j.spi.DelimitedOptionHandler;
import org.kohsuke.args4j.spi.OneArgumentOptionHandler;
import org.kohsuke.args4j.spi.Setter;

/**
 * An {@code OptionHandler} that accepts a list of values to add to an underlying collection option
 * value.
 *
 * <p>This handler interprets the raw option value as a comma-delimited list and passes the
 * individual list values to a delegate {@link ItemParser} strategy to obtain collection members
 * from.
 *
 * @param <T> The type of the underlying option values stored in the container.
 */
public class CollectionOptionHandler<T> extends DelimitedOptionHandler<T> {

  /**
   * A strategy for parsing an individual option value from a {@link String}.
   *
   * @param <T> The type of the underlying option value.
   */
  public interface ItemParser<T> {

    /** Parses {@link String Strings} to themselves. */
    ItemParser<String> IDENTITY =
        new ItemParser<String>() {
          @Override
          public String parse(String item) {
            return item;
          }
        };

    /**
     * Converts an individual item from an option list into an instance of {@code T}.
     *
     * @param item An individual raw value to parse.
     * @return The parsed value.
     */
    T parse(String item);
  }

  /**
   * @param parser The parser being used to parse this option.
   * @param option Metadata describing the option being parsed.
   * @param setter A helper that can add parsed values to the underlying collection option value.
   * @param defaultMetaVariable The default meta variable to use to describe the individual items in
   *     the collection.
   * @param itemParser The strategy for parsing individual option values with to populate the
   *     underlying collection option value with.
   */
  public CollectionOptionHandler(
      CmdLineParser parser,
      OptionDef option,
      Setter<? super T> setter,
      final String defaultMetaVariable,
      final ItemParser<T> itemParser) {

    super(
        parser,
        option,
        setter,
        ",",
        new OneArgumentOptionHandler<T>(parser, option, setter) {
          @Override
          protected T parse(String argument) {
            return itemParser.parse(argument);
          }

          @Override
          public String getDefaultMetaVariable() {
            return defaultMetaVariable;
          }
        });
  }
}
