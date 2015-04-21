/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.complete._
import sbt.Keys._
import sbt.Project.Initialize

object Scriptit {
  import Script._

  val scriptitBase = settingKey[File]("scriptit-base")
  val scriptitTestName = settingKey[String]("scriptit-test-name")
  val scriptitCommands = taskKey[Seq[Command]]("scriptit-commands")
  val scriptitScalaVersions = settingKey[Seq[String]]("scriptit-scala-versions")
  val scriptitProperties = taskKey[Map[String, String]]("scriptit-properties")
  val scriptit = inputKey[Unit]("scriptit")

  lazy val settings: Seq[Setting[_]] = Seq(
    scriptitBase := sourceDirectory.value / "scriptit",
    scriptitTestName := "test",
    scriptitCommands := Commands.defaultCommands,
    scriptitCommands += Commands.zincCommand(Dist.create.value),
    scriptitScalaVersions := Seq("2.9.3", "2.10.3", "2.11.0-RC3"),
    scriptitProperties := scalaProperties(appConfiguration.value, scriptitScalaVersions.value),
    scriptitProperties ++= javaProperties,
    scriptit <<= scriptitTask
  )

  def scriptitTask = InputTask((scriptitBase, scriptitTestName)((dir, name) => (s: State) => scriptitParser(dir, name))) { input =>
    (scriptitBase, scriptitTestName, scriptitCommands, scriptitProperties, input, streams) map { (base, scriptName, commands, properties, args, s) =>
      val tests = if (args.isEmpty) scriptitTests(base, scriptName) else args
      val parse = new ScriptParser
      val results = tests map { test =>
        val dir = base / test
        val scriptFile = dir / scriptName
        val script = parse(IO.read(scriptFile))
        withTestDirectory(dir)(runTest(test, scriptFile.getPath, script, commands, properties, s.log))
      }
      val failed = results count (r => !r.success)
      if (failed > 0) {
        val counted = this.counted("test", "", "s", failed).getOrElse("test")
        sys.error(counted + " failed")
      }
    }
  }

  private def counted(prefix: String, single: String, plural: String, count: Int): Option[String] = count match {
    case 0 => None
    case 1 => Some("1 " + prefix + single)
    case x => Some(x.toString + " " + prefix + plural)
  }

  def scriptitParser(scriptitBase: File, script: String): Parser[Seq[String]] =
    Defaults.distinctParser(scriptitTests(scriptitBase, script).toSet, raw = false)

  def scriptitTests(scriptitBase: File, script: String): Seq[String] =
    (scriptitBase ** script).get map (_.getParentFile) pair relativeTo(scriptitBase) map (_._2)

  def runTest(name: String, path: String, script: Seq[Line], commands: Seq[Command], properties: Map[String, String], log: Logger)(dir: File): Result = {
    val runner = new ScriptRunner(name, path, script)
    runner.run(dir, commands, properties, log)
  }

  def withTestDirectory[T](originalDir: File)(action: File => T): T = {
    require(originalDir.isDirectory)
    IO.withTemporaryDirectory { temporary =>
      val testDir = temporary / originalDir.getName
      IO.copyDirectory(originalDir, testDir)
      action(testDir)
    }
  }

  def scalaProperties(config: xsbti.AppConfiguration, versions: Seq[String]): Map[String, String] = {
    (versions flatMap { version =>
      val binaryVersion = CrossVersion.binaryVersion(version, "")
      val provider = config.provider.scalaProvider.launcher.getScala(version)
      def property(name: String) = "scala.%s.%s" format (binaryVersion, name)
      Seq(
        property("library") -> provider.libraryJar.getAbsolutePath,
        property("compiler") -> provider.compilerJar.getAbsolutePath,
        property("extra") -> Path.makeString((provider.jars.toSet - provider.libraryJar - provider.compilerJar).toSeq),
        property("path") -> Path.makeString(provider.jars),
        property("home") -> provider.libraryJar.getParentFile.getParentFile.getAbsolutePath
      )
    }).toMap
  }

  def javaProperties: Map[String, String] = {
    val javaHome = Option(System getenv "JAVA_HOME") orElse Option(System getProperty "java.home") getOrElse ""
    Map("java.home" -> javaHome)
  }
}

object Script {

  //
  // Parsing
  //

  import scala.util.parsing.combinator._
  import scala.util.parsing.input.Position

  case class Source(start: Position, end: Position, text: String)

  sealed trait Line
  case class Comment(text: String) extends Line
  case class Statement(command: String, arguments: List[String], negative: Boolean) extends Line
  case class Empty(space: String) extends Line
  case class Sourced[A <: Line](parsed: A, source: Source) extends Line

  class ParseException(msg: String) extends RuntimeException(msg)

  object ScriptParser {
    val CommentMarker   = "#"
    val NegativeMarker  = "!"
    val SingleQuoteChar = '\''
    val DoubleQuoteChar = '\"'
    val NewlineChar     = '\n'
    val ReturnChar      = '\r'
    val EofChar         = '\032'
    val ExcludedChars   = Set(NewlineChar, ReturnChar, EofChar)
  }

  class ScriptParser extends RegexParsers {
    import ScriptParser._

    override def skipWhitespace = false

    lazy val lines: Parser[List[Line]] = repsep(line, lineEnd)
    lazy val line: Parser[Line] = comment | sourcedStatement | empty
    lazy val lineEnd: Parser[String] = optSpace <~ newline

    lazy val comment: Parser[Comment] = optSpace ~> CommentMarker ~> anyString ^^ Comment

    lazy val sourcedStatement: Parser[Sourced[Statement]] = sourcedLine(statement)

    lazy val statement: Parser[Statement] = optSpace ~> negative ~ command ~ arguments ^^ {
      case negative ~ command ~ arguments => Statement(command, arguments, negative)
    }

    lazy val negative: Parser[Boolean] = NegativeMarker <~ optSpace ^^^ true | success(false)
    lazy val command: Parser[String] = token
    lazy val arguments: Parser[List[String]] = rep(space ~> token)

    lazy val token: Parser[String] = singleQuoted | doubleQuoted | word
    lazy val singleQuoted: Parser[String] = quoted(SingleQuoteChar)
    lazy val doubleQuoted: Parser[String] = quoted(DoubleQuoteChar)
    lazy val word: Parser[String] = """\S+""".r

    lazy val empty: Parser[Empty] = optSpace ^^ Empty

    lazy val space: Parser[String]    = """[ \t]+""".r
    lazy val optSpace: Parser[String] = """[ \t]*""".r
    lazy val newline: Parser[String]  = """\s*[\n\r]""".r

    lazy val any: Parser[Elem] = elem("any", x => !(ExcludedChars contains x))
    lazy val anyString: Parser[String] = rep(any) ^^ { _.mkString }

    def anyExcept(e: Elem): Parser[Elem] = elem("anyExcept", x => !(ExcludedChars contains x) && (x != e))
    def escaped(c: Char): Parser[String] = "\\" + c
    def quoted(q: Char): Parser[String] = q ~> rep(escaped(q) | anyExcept(q)) <~ q ^^ { _.mkString.replace("\\"+q, ""+q) }

    def sourcedLine[A <: Line](parser: => Parser[A]): Parser[Sourced[A]] = sourced(parser)(Sourced.apply)

    def sourced[A, B](parser: => Parser[A])(withSource: (A, Source) => B): Parser[B] = Parser { input =>
      parser(input) match {
        case Success(result, next) =>
          val text = input.source.subSequence(input.offset, next.offset).toString
          val source = Source(input.pos, next.pos, text)
          Success(withSource(result, source), next)
        case failed: NoSuccess => failed
      }
    }

    def apply(script: String): List[Line] = apply(script, e => throw new ParseException(e))

    def apply(script: String, onError: String => Unit): List[Line] = {
      parseAll(lines, script) match {
        case Success(result, _) => result
        case NoSuccess(msg, _)  => onError(msg); Nil
      }
    }
  }

  //
  // Running
  //

  import java.io.{ BufferedReader, InputStream, InputStreamReader, IOException, StringWriter }
  import java.lang.{ ProcessBuilder => JProcessBuilder }
  import scala.annotation.tailrec
  import scala.Console.{ BLUE, GREEN, RED, RESET }

  type Action = (File, Seq[String]) => Result
  case class Command(name: String, action: Action)

  sealed trait Result {
    def output: String
    def success: Boolean
  }

  case class Success(output: String) extends Result { def success = true }
  case class Failure(output: String) extends Result { def success = false }

  class ScriptRunner(name: String, path: String, script: Seq[Line]) {
    val Property = """(.*)\{\{(.+)\}\}(.*)""".r

    def run(dir: File, commands: Seq[Command], properties: Map[String, String], log: Logger): Result = {
      val blue    = coloured(log, BLUE)
      val green   = coloured(log, GREEN)
      val red     = coloured(log, RED)
      val comment = blue("#")
      val success = green(" + ")
      val failure = red("! ")
      val indent  = "  "

      def succeeded(source: Source, output: String) = {
        log.info(success + source.text)
        for (line <- output.split("""\n""")) log.debug(indent + line)
      }

      def failed(source: Source, output: String) = {
        log.error(failure + source.text)
        log.error(indent + path + ":" + source.start.line)
        for (line <- output.split("""\n""")) log.error(indent + line)
      }

      @tailrec
      def process(lines: Seq[Line]): Result = {
        if (lines.isEmpty) Success("Test passed")
        else lines.head match {
          case Comment(text) =>
            log.debug(comment + text)
            process(lines.tail)
          case Sourced(Statement(cmd, args, failureExpected), source) =>
            commands find (_.name == cmd) match {
              case Some(command) =>
                val as = args map replaceProperties(properties)
                val result = command.action(dir, as)
                val successful = result.success != failureExpected
                if (successful) {
                  succeeded(source, result.output)
                  process(lines.tail)
                } else {
                  failed(source, result.output)
                  Failure("Test failed")
                }
              case None =>
                failed(source, "Script command not found: " + cmd)
                Failure("Unknown command")
            }
          case _ => process(lines.tail)
        }
      }

      log.info(blue(name))
      process(script)
    }

    def coloured(log: Logger, colour: String) = (text: String) => if (log.ansiCodesSupported) (colour + text + RESET) else text

    def replaceProperties(properties: Map[String, String])(arg: String): String = {
      def replace(s: String): String = s match {
        case Property(before, property, after) => replace(before + getProperty(property, properties) + after)
        case _ => s
      }
      replace(arg)
    }

    def getProperty(property: String, properties: Map[String, String]): String = {
      properties get property orElse Option(System getProperty property) getOrElse ""
    }
  }

  object Commands {
    val defaultCommands: Seq[Command] = Seq(
      Command("mkdir", mkdir),
      Command("copy", copy),
      Command("exists", exists),
      Command("delete", delete),
      Command("show", show),
      Command("sleep", sleep)
    )

    def zincCommand(dist: File) = Command("zinc", zinc(dist))

    def zinc(dist: File)(baseDir: File, args: Seq[String]): Result = {
      val zinc = dist / "bin" / "zinc"
      run(zinc.getAbsolutePath +: args, baseDir)
    }

    def run(command: Seq[String], cwd: File): Result = {
      val builder = new JProcessBuilder(command.toArray: _*)
      builder.directory(cwd)
      builder.redirectErrorStream(true)
      val process = builder.start()
      val stream = process.getInputStream
      process.waitFor()
      val output = readFully(stream)
      val exitCode = process.exitValue
      if (exitCode == 0) Success(output) else Failure(output)
    }

    def readFully(stream: InputStream): String = {
      val writer = new StringWriter
      if (stream ne null) {
        val buffer = new Array[Char](1024)
        try {
          val reader = new BufferedReader(new InputStreamReader(stream))
          var n = 0
          while ({ n = reader.read(buffer); n != -1 }) {
            writer.write(buffer, 0, n)
          }
        } catch {
          case e: IOException =>
        } finally {
          stream.close()
        }
      }
      writer.toString()
    }

    def mkdir(baseDir: File, paths: Seq[String]): Result = {
      val failed = paths filter (path => !createDir(pathToFile(baseDir, path)))
      if (failed.isEmpty) Success("Created directories: " + listed(paths))
      else Failure("Could not create directories: " + listed(failed))
    }

    def createDir(dir: File): Boolean = {
      try { IO.createDirectory(dir); true }
      catch { case e: Exception => false }
    }

    def copy(baseDir: File, paths: Seq[String]): Result = {
      if (paths.size < 2) Failure("Need at least two paths for copy")
      else {
        val sourcePaths = paths.init
        val destPath = paths.last
        val destination = pathToFile(baseDir, destPath)
        if (destination.isDirectory) {
          val sources = pathsToFiles(baseDir, sourcePaths)
          val mapped = sourcePaths zip sources map { case (p, f) => (p, f, new File(destination, f.getName)) }
          val failed = mapped filter { case (path, from, to) => !copyFile(from, to) }
          if (failed.isEmpty) Success("Copied %s to %s" format (listed(sourcePaths), destPath))
          else Failure("Could not copy %s to %s" format (listed(failed.map(_._1)), destPath))
        } else {
          if (sourcePaths.size > 1) Failure("Only one source possible when destination is not a directory")
          else {
            val sourcePath = sourcePaths.head
            val source = pathToFile(baseDir, sourcePath)
            if (copyFile(source, destination)) Success("Copied %s to %s" format (sourcePath, destPath))
            else Failure("Could not copy %s to %s" format (sourcePath, destPath))
          }
        }
      }
    }

    def copyFile(from: File, to: File): Boolean = {
      try {
        if (from.isDirectory) IO.copyDirectory(from, to)
        else IO.copyFile(from, to)
        true
      } catch {
        case e: Exception => false
      }
    }

    def exists(baseDir: File, paths: Seq[String]): Result = {
      val absent = paths filter (path => !pathToFile(baseDir, path).exists)
      if (absent.isEmpty) Success("Files exist: " + listed(paths))
      else Failure("Files do not exist: " + listed(absent))
    }

    def delete(baseDir: File, paths: Seq[String]): Result = {
      val failed = paths filter (path => !deleteFile(pathToFile(baseDir, path)))
      if (failed.isEmpty) Success("Deleted: " + listed(paths))
      else Failure("Could not delete: " + listed(failed))
    }

    def deleteFile(file: File): Boolean = {
      val existed = file.exists
      IO.delete(file)
      existed
    }

    def show(baseDir: File, paths: Seq[String]): Result = {
      val output = paths map (path => showFile(pathToFile(baseDir, path)))
      Success(output mkString "\n")
    }

    def showFile(file: File): String = {
      val path = file.getAbsolutePath + ":\n"
      val contents = if (file.exists) IO.read(file) else ""
      path + contents
    }

    def sleep(baseDir: File, args: Seq[String]): Result = {
      if (args.size != 1) {
        Failure("Couldn't sleep without just one duration")
      } else {
        val arg = args.head
        val d = duration(arg, 0)
        if (d != 0) {
          Thread.sleep(d)
          Success("Slept for " + arg)
        } else {
          Failure("Couldn't sleep: " + listed(args))
        }
      }
    }

    def duration(arg: String, default: Long): Long = {
      val Duration = """(\d+)([hms]?)""".r
      arg match {
        case Duration(length, unit) =>
          val multiplier = unit match {
            case "h" => 60 * 60 * 1000
            case "m" => 60 * 1000
            case "s" => 1000
            case _ => 1
          }
          try { length.toLong * multiplier } catch { case _: Exception => default }
        case _ => default
      }
    }

    def pathsToFiles(baseDir: File, paths: Seq[String]): Seq[File] = paths map (pathToFile(baseDir, _))

    def pathToFile(baseDir: File, path: String): File = {
      val file = new File(path)
      if (file.isAbsolute) file else new File(baseDir, path)
    }

    def listed(elements: Seq[String]): String = elements.mkString("[ ", ",  ", " ]")
  }
}
