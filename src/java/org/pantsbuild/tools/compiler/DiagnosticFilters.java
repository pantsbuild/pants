// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.compiler;

import java.util.Locale;
import java.util.regex.Pattern;

import javax.tools.Diagnostic;
import javax.tools.FileObject;

/**
 * A utility for constructing {@link DiagnosticFilter DiagnosticFilters}.
 */
final class DiagnosticFilters {

  /**
   * Indicates the treatment that should be applied to a diagnostic.
   * <ul>
   *   <li>{@link #IGNORE} indicates the diagnostic should be ignored.
   *   <li>{@link #PASS} ndicates a filter passes on categorizing a diagnostic.
   * </ul>
   *
   * All other treatments map to a {@link Diagnostic.Kind} of the same name.
   */
  public enum Treatment {
    // Diagnostic.Kind equivalents
    NOTE,
    WARNING,
    MANDATORY_WARNING,
    ERROR,
    OTHER,

    /**
     * Indicates a diagnostic should be dropped.
     */
    IGNORE,

    /**
     * Indicates a {@link DiagnosticFilter} passes on treatment assignment to the next filter.
     */
    PASS
  }

  /**
   * A filter for diagnostics that can signal a diagnostic be skipped or alter its treatment by
   * a downstream {@link javax.tools.DiagnosticListener}.
   *
   * @param <T>
   */
  interface DiagnosticFilter<T> {

    /**
     * Reports the appropriate treatment for the given diagnostic.
     *
     * @param diagnostic The diagnostic to categorize.
     * @return A suggested treatment for the diagnostic or {@link Treatment#PASS} to pass the
     *     categorization to the next filter.
     */
    Treatment categorize(Diagnostic<? extends T> diagnostic);
  }

  /**
   * A predicate that tests if values of type {@code T} are permitted to pass through to the guarded
   * code.
   *
   * @param <T> The type of values the guard tests.
   */
  interface Guard<T> {

    /**
     * Tests if the given item is permitted to pass through to some guarded code.
     *
     * @param item the item to test.
     * @return {@code true} if the item is permitted to pass through to the guarded code.
     */
    boolean permit(T item);
  }

  /**
   * A filter that maps each {@link Diagnostic.Kind} straight to its obvious {@link Treatment}
   * counterpart and never returns {@link Treatment#IGNORE} or {@link Treatment#PASS}.
   */
  static final DiagnosticFilter<Object> STRAIGHT_MAPPING = new DiagnosticFilter<Object>() {
    @Override public Treatment categorize(Diagnostic<?> diagnostic) {
      Treatment treatment;
      switch (diagnostic.getKind()) {
        case NOTE:
          treatment = Treatment.NOTE;
          break;
        case WARNING:
          treatment = Treatment.WARNING;
          break;
        case MANDATORY_WARNING:
          treatment = Treatment.MANDATORY_WARNING;
          break;
        case ERROR:
          treatment = Treatment.ERROR;
          break;
        case OTHER:
        default:
          treatment = Treatment.OTHER;
      }
      return treatment;
    }
  };

  private DiagnosticFilters() {
    // utility
  }

  static <S> DiagnosticFilter<S> combine(
      final Iterable<? extends DiagnosticFilter<? super S>> filters) {

    return new DiagnosticFilter<S>() {
      @Override public Treatment categorize(Diagnostic<? extends S> diagnostic) {
        for (DiagnosticFilter<? super S> filter : filters) {
          Treatment treatment = filter.categorize(diagnostic);
          if (Treatment.PASS != treatment) {
            return treatment;
          }
        }
        return STRAIGHT_MAPPING.categorize(diagnostic);
      }
    };
  }

  static <T extends FileObject> DiagnosticFilter<T> guarded(final DiagnosticFilter<T> guarded,
      final Guard<Diagnostic<? extends T>> guard) {

    return new DiagnosticFilter<T>() {
      @Override public Treatment categorize(Diagnostic<? extends T> diagnostic) {
        return guard.permit(diagnostic) ? guarded.categorize(diagnostic) : Treatment.PASS;
      }
    };
  }

  static <T extends FileObject> DiagnosticFilter<T> ignorePathPrefixes(
      final Iterable<String> pathPrefixes) {

    return new DiagnosticFilter<T>() {
      @Override public Treatment categorize(Diagnostic<? extends T> diagnostic) {
        FileObject source = diagnostic.getSource();
        if (source != null) {
          // URI's need not have a path in general and in practice diagnostics get emitted for
          // jar:// sources that in fact do not have a path - guard against these cases since we
          // only need to match against file:// to satisfy this filter.
          String path = source.toUri().getPath();
          if (path != null) {
            for (String pathPrefix : pathPrefixes) {
              if (path.startsWith(pathPrefix)) {
                return Treatment.IGNORE;
              }
            }
          }
        }
        return Treatment.PASS;
      }
    };
  }

  static <T extends FileObject> DiagnosticFilter<T> ignoreMessagesMatching(
      final Iterable<Pattern> regexes) {

    return new DiagnosticFilter<T>() {
      @Override public Treatment categorize(Diagnostic<? extends T> diagnostic) {
        String message = diagnostic.getMessage(Locale.getDefault());
        for (Pattern regex : regexes) {
          if (regex.matcher(message).matches()) {
            return Treatment.IGNORE;
          }
        }
        return Treatment.PASS;
      }
    };
  }
}
