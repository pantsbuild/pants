/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.options

import java.io.File

trait OptionSet[T] {
  /** An empty set of options. */
  def empty: T

  /** Apply any residual entries to an instance of T and return a new T. */
  def applyResidual(t: T, residualArgs: Seq[String]): T =
    if (residualArgs.nonEmpty) {
      throw new RuntimeException(
        s"Unexpected residual arguments: ${residualArgs.mkString("[", ", ", "]")}"
      )
    } else {
      t
    }

  /** All available command-line options. */
  def options: Seq[OptionDef[T]]

  private def allOptions: Set[OptionDef[T]] = options.toSet

  /**
   * Print out the usage message.
   */
  def printUsage(cmdName: String, residualArgs: String = ""): Unit = {
    val column = options.map(_.length).max + 2
    println(s"Usage: ${cmdName} <options> ${residualArgs}")
    options foreach { opt => if (opt.extraline) println(); println(opt.usage(column)) }
    println()
  }

  /**
   * Anything starting with '-' is considered an option, not a source file.
   */
  private def isOpt(s: String) = s startsWith "-"

  /**
   * Parse all args into a T.
   * Residual args are either unknown options or applied.
   */
  def parse(args: Seq[String]): Parsed[T] = {
    val Parsed(instance, remaining, errors) = Options.parse(empty, allOptions, args, stopOnError = false)
    val (unknown, residual) = remaining partition isOpt
    val unknownErrors = unknown map ("Unknown option: " + _)
    Parsed(applyResidual(instance, residual), Seq.empty, errors ++ unknownErrors)
  }

  // helpers for creating options

  def boolean(opt: String, desc: String, action: T => T) = new BooleanOption[T](Seq(opt), desc, action)
  def boolean(opts: (String, String), desc: String, action: T => T) = new BooleanOption[T](Seq(opts._1, opts._2), desc, action)
  def string(opt: String, arg: String, desc: String, action: (T, String) => T) = new StringOption[T](Seq(opt), arg, desc, action)
  def int(opt: String, arg: String, desc: String, action: (T, Int) => T) = new IntOption[T](Seq(opt), arg, desc, action)
  def double(opt: String, arg: String, desc: String, action: (T, Double) => T) = new DoubleOption[T](Seq(opt), arg, desc, action)
  def fraction(opt: String, arg: String, desc: String, action: (T, Double) => T) = new FractionOption[T](Seq(opt), arg, desc, action)
  def file(opt: String, arg: String, desc: String, action: (T, File) => T) = new FileOption[T](Seq(opt), arg, desc, action)
  def path(opt: String, arg: String, desc: String, action: (T, Seq[File]) => T) = new PathOption[T](Seq(opt), arg, desc, action)
  def path(opts: (String, String), arg: String, desc: String, action: (T, Seq[File]) => T) = new PathOption[T](Seq(opts._1, opts._2), arg, desc, action)
  def prefix(pre: String, arg: String, desc: String, action: (T, String) => T) = new PrefixOption[T](pre, arg, desc, action)
  def filePair(opt: String, arg: String, desc: String, action: (T, (File, File)) => T) = new FilePairOption[T](Seq(opt), arg, desc, action)
  def fileMap(opt: String, desc: String, action: (T, Map[File, File]) => T) = new FileMapOption[T](Seq(opt), desc, action)
  def fileSeqMap(opt: String, desc: String, action: (T, Map[Seq[File], File]) => T) = new FileSeqMapOption[T](Seq(opt), desc, action)
  def header(label: String) = new HeaderOption[T](label)
  def dummy(opt: String, desc: String) = new DummyOption[T](opt, desc)
}
