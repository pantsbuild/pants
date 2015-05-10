// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.compiler;

import java.util.Locale;

import javax.tools.Diagnostic;
import javax.tools.Diagnostic.Kind;
import javax.tools.DiagnosticListener;

import org.pantsbuild.tools.compiler.DiagnosticFilters.DiagnosticFilter;
import org.pantsbuild.tools.compiler.DiagnosticFilters.Treatment;

/**
 * A DiagnosticListener that supports filtering and promotion or demotion of diagnostics.
 *
 * <p>By default no diagnostics are filtered or otherwise rank-adjusted, use
 * {@link #setFilter(DiagnosticFilter)} to change this.
 *
 * @param <T> The type of diagnostic this listener can handle.
 */
abstract class FilteredDiagnosticListener<T> implements DiagnosticListener<T> {

  /**
   * A diagnostic wrapper that replaces the wrapped diagnostic's {@link Diagnostic#getKind() kind}.
   */
  class FilteredDiagnostic implements Diagnostic<T> {
    private final Kind filteredKind;
    private final Diagnostic<? extends T> delegate;

    FilteredDiagnostic(Kind filteredKind, Diagnostic<? extends T> delegate) {
      this.filteredKind = filteredKind;
      this.delegate = delegate;
    }

    @Override
    public Kind getKind() {
      return filteredKind;
    }

    @Override
    public T getSource() {
      return delegate.getSource();
    }

    @Override
    public long getPosition() {
      return delegate.getPosition();
    }

    @Override
    public long getStartPosition() {
      return delegate.getStartPosition();
    }

    @Override
    public long getEndPosition() {
      return delegate.getEndPosition();
    }

    @Override
    public long getLineNumber() {
      return delegate.getLineNumber();
    }

    @Override
    public long getColumnNumber() {
      return delegate.getColumnNumber();
    }

    @Override
    public String getCode() {
      return delegate.getCode();
    }

    @Override
    public String getMessage(Locale locale) {
      return delegate.getMessage(locale);
    }
  }

  private volatile DiagnosticFilter<? super T> filter = DiagnosticFilters.STRAIGHT_MAPPING;

  /**
   * Set the filter to use for all subsequent reporting.
   *
   * @param filter The filter to use for all subsequent reporting.
   */
  void setFilter(final DiagnosticFilter<? super T> filter) {
    if (filter == null) {
      throw new NullPointerException("The filter cannot be null.");
    }

    this.filter = new DiagnosticFilter<T>() {
      @Override public Treatment categorize(Diagnostic<? extends T> diagnostic) {
        Treatment treatment = filter.categorize(diagnostic);
        if (Treatment.PASS != treatment) {
          return treatment;
        }
        // Backstop with a mapping guaranteed not to ignore or pass
        return DiagnosticFilters.STRAIGHT_MAPPING.categorize(diagnostic);
      }
    };
  }

  @Override
  public final void report(Diagnostic<? extends T> diagnostic) {
    Treatment treatment = filter.categorize(diagnostic);
    switch (treatment) {
      case IGNORE:
        break;
      case NOTE:
        reportOn(new FilteredDiagnostic(Kind.NOTE, diagnostic));
        break;
      case WARNING:
        reportOn(new FilteredDiagnostic(Kind.WARNING, diagnostic));
        break;
      case MANDATORY_WARNING:
        reportOn(new FilteredDiagnostic(Kind.MANDATORY_WARNING, diagnostic));
        break;
      case ERROR:
        reportOn(new FilteredDiagnostic(Kind.ERROR, diagnostic));
        break;
      case OTHER:
      default:
        reportOn(new FilteredDiagnostic(Kind.OTHER, diagnostic));
    }
  }

  /**
   * Subclasses should override and handle reporting of the given diagnostic.
   *
   *  @param diagnostic The diagnostic to report.
   */
  protected abstract void reportOn(Diagnostic<? extends T> diagnostic);
}
