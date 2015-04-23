/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import scala.annotation.tailrec

/**
 * Parsing command-line options, immutably.
 */
object Options {
  def parse[Context](context: Context, options: Set[OptionDef[Context]], args: Seq[String], stopOnError: Boolean): Parsed[Context] =
    parseOptions(context, options, args, Seq.empty, Seq.empty, stopOnError)

  @tailrec
  def parseOptions[Context](context: Context, options: Set[OptionDef[Context]], args: Seq[String], residual: Seq[String], errors: Seq[String], stopOnError: Boolean): Parsed[Context] = {
    if (args.isEmpty || (stopOnError && !errors.isEmpty)) {
      Parsed(context, residual, errors)
    } else {
      val arg = args.head
      options find (_ claims arg) match {
        case Some(option) =>
          val parsed = option.process(context, args)
          parseOptions(parsed.context, options, parsed.remaining, residual, errors ++ parsed.errors, stopOnError)
        case None =>
          parseOptions(context, options, args.tail, residual :+ arg, errors, stopOnError)
      }
    }
  }
}

case class Parsed[Context](context: Context, remaining: Seq[String], errors: Seq[String] = Seq.empty)

abstract class OptionDef[Context] {
  def options: Seq[String]
  def description: String
  def process(context: Context, args: Seq[String]): Parsed[Context]

  def claims(option: String): Boolean = options contains option
  def help: String = options mkString (" | ")
  def length: Int = help.length
  def usage(column: Int): String = ("  " + help.padTo(column, ' ') + description)
  def extraline: Boolean = false
}

abstract class FlagOption[Context] extends OptionDef[Context] {
  def action: Context => Context
  def process(context: Context, args: Seq[String]) = Parsed(action(context), args.tail)
}

abstract class ArgumentOption[Value, Context] extends OptionDef[Context] {
  def argument: String
  def parse(arg: String): Option[Value]
  def action: (Context, Value) => Context

  def process(context: Context, args: Seq[String]): Parsed[Context] = {
    val rest = args.tail
    def error = Parsed(context, rest, Seq(invalid))
    if (rest.isEmpty) error
    else parse(rest.head) match {
      case Some(value) => Parsed(action(context, value), rest.tail)
      case None        => error
    }
  }

  def invalid = "Invalid option for " + options.headOption.getOrElse("")

  override def help = options.mkString(" | ") + " <" + argument + ">"
}

class BooleanOption[Context](
  val options: Seq[String],
  val description: String,
  val action: Context => Context)
extends FlagOption[Context]

class StringOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, String) => Context)
extends ArgumentOption[String, Context] {
  def parse(arg: String): Option[String] = {
    Some(arg)
  }
}

class IntOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, Int) => Context)
extends ArgumentOption[Int, Context] {
  def parse(arg: String): Option[Int] = {
    try { Some(arg.toInt) }
    catch { case _: NumberFormatException => None }
  }
}

class DoubleOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, Double) => Context)
extends ArgumentOption[Double, Context] {
  def parse(arg: String): Option[Double] = {
    try { Some(arg.toDouble) }
    catch { case _: NumberFormatException => None }
  }
}

class FractionOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, Double) => Context)
extends ArgumentOption[Double, Context] {
  def parse(arg: String): Option[Double] = {
    try {
      val fraction = arg.toDouble
      if (fraction < 0.0 || fraction > 1.0) None else Some(fraction)
    } catch { case _: NumberFormatException => None }
  }
}

class FileOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, File) => Context)
extends ArgumentOption[File, Context] {
  def parse(arg: String): Option[File] = {
    Some(new File(arg))
  }
}

class PathOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, Seq[File]) => Context)
extends ArgumentOption[Seq[File], Context] {
  def parse(arg: String): Option[Seq[File]] = ParseHelpers.parseFileSeq(arg)
}

class PrefixOption[Context](
  val prefix: String,
  val argument: String,
  val description: String,
  val action: (Context, String) => Context)
extends OptionDef[Context] {
  def options = Seq(prefix)

  override def claims(option: String) = option startsWith prefix

  def process(context: Context, args: Seq[String]): Parsed[Context] = {
    val prefixed = args.head.substring(prefix.length)
    Parsed(action(context, prefixed), args.tail)
  }

  override def help = prefix + argument
}

class FilePairOption[Context](
  val options: Seq[String],
  val argument: String,
  val description: String,
  val action: (Context, (File, File)) => Context)
extends ArgumentOption[(File, File), Context] {
  val pairSeparator = File.pathSeparatorChar

  def parse(arg: String): Option[(File, File)] = {
    val p = arg split pairSeparator
    if (p.length == 2) Some((new File(p(0)), new File(p(1)))) else None
  }
}

class FileMapOption[Context](
  val options: Seq[String],
  val description: String,
  val action: (Context, Map[File, File]) => Context)
extends ArgumentOption[Map[File, File], Context] {
  val argument = "mapping"

  val argSeparator = ','
  val pairSeparator = File.pathSeparatorChar

  def parse(arg: String): Option[Map[File, File]] = {
    val pairs = arg split argSeparator
    val files = pairs map parseFilePair
    if (files exists (_.isEmpty)) None else Some(files.flatten.toMap)
  }

  def parseFilePair(pair: String): Option[(File, File)] = {
    val p = pair split pairSeparator
    p.length match {
      case 1 => Some((new File(p(0)), new File("")))
      case 2 => Some((new File(p(0)), new File(p(1))))
      case _ => None
    }
  }
}

class FileSeqMapOption[Context](
  val options: Seq[String],
  val description: String,
  val action: (Context, Map[Seq[File], File]) => Context)
        extends ArgumentOption[Map[Seq[File], File], Context] {
  val argument = "mapping"

  val argSeparator = ','
  val openSeq = '{'
  val closeSeq = '}'
  val pairSeparator = File.pathSeparatorChar

  def parse(arg: String): Option[Map[Seq[File], File]] = {
    val pairs = arg split argSeparator
    val files = pairs map parseFileSeqPair
    if (files exists (_.isEmpty)) None else Some(files.flatten.toMap)
  }

  def parseFileSeqPair(pair: String): Option[(Seq[File], File)] = {
    val pairSeparatorIdx = pair lastIndexOf pairSeparator
    if (pairSeparatorIdx == -1) {
      None
    } else {
      val p = Array(pair.substring(0, pairSeparatorIdx), pair.substring(pairSeparatorIdx + 1))
      parseFileSeq(p(0)) match {
        case Some(fileSeq) => Some((fileSeq, new File(p(1))))
        case None => None
      }
    }
  }

  def parseFileSeq(arg: String): Option[Seq[File]] = {
    val seqArg = if (arg.head == openSeq && arg.last == closeSeq) arg.init.tail else arg
    ParseHelpers.parseFileSeq(seqArg)
  }
}

class HeaderOption[Context](
  val header: String)
extends OptionDef[Context] {
  def options: Seq[String] = Seq.empty
  def description = ""
  def process(context: Context, args: Seq[String]) = Parsed(context, args.tail)
  override def claims(option: String): Boolean = false
  override def help = ""
  override def length = 0
  override def usage(column: Int) = header
  override def extraline = true
}

class DummyOption[Context](
  val optionHelp: String,
  val description: String)
extends OptionDef[Context] {
  def options: Seq[String] = Seq.empty
  def process(context: Context, args: Seq[String]) = Parsed(context, args.tail)
  override def claims(option: String): Boolean = false
  override def help = optionHelp
}

object ParseHelpers {
  def parseFileSeq(arg: String): Option[Seq[File]] = {
    val expanded = scala.tools.nsc.util.ClassPath.expandPath(arg)
    val files = expanded map (new File(_))
    Some(files)
  }
}
