package pants.contrib.bloop.compile

import ammonite.ops._
import bloop.bsp.BloopLanguageClient
import bloop.bsp.BloopLanguageServer
import bloop.internal.build.BuildInfo
import bloop.launcher.LauncherMain
import bloop.launcher.core.{Installer, Shell}
import bloop.launcher.util.Environment
import bloop.logging.BspClientLogger
import bloop.logging.DebugFilter
import bloop.logging.Logger
import ch.epfl.scala.bsp
import ch.epfl.scala.bsp.endpoints
import io.circe.Encoder
import io.circe.derivation.JsonCodec
import io.circe.syntax._
import io.circe._
import monix.eval.Task
import monix.execution.Ack
import monix.execution.ExecutionModel
import monix.execution.Scheduler
import sbt.internal.util.{BasicLogger, ConsoleLogger, ConsoleOut, StackTrace}
import sbt.util.{ControlEvent, Level, LogEvent}

import scala.concurrent.Await
import scala.concurrent.duration.FiniteDuration
import scala.concurrent.ExecutionContext.Implicits.global
import scala.concurrent.Promise
import scala.meta.jsonrpc._

import java.io.PipedInputStream
import java.io.PipedOutputStream
import java.nio.charset.StandardCharsets
import java.util.concurrent.Executors

// TODO: this is in https://github.com/pantsbuild/pants/pull/7506 -- merge that!!
case class BareBonesLogger(thisLevel: Level.Value) extends bloop.logging.Logger {
  import scala.Console.{ CYAN, GREEN, RED, YELLOW, RESET }

  val out = System.err

  def printError(message: => String): Unit = {
    val colored = s"$RED[error] $message$RESET"
    out.println(colored)
  }

  override def printDebug(message: String): Unit = log(Level.Debug, message)

  override def asDiscrete: Logger = BareBonesLogger(Level.Info)

  override def asVerbose: Logger = BareBonesLogger(Level.Debug)

  override def debug(message: String)(implicit _ctx: DebugFilter): Unit = log(Level.Debug, message)

  override def debugFilter: DebugFilter = DebugFilter.All

  override def isVerbose: Boolean = thisLevel >= Level.Debug

  override def name: String = "pants-bloop-logger"

  override def ansiCodesSupported(): Boolean = true

  override def error(message: String): Unit = log(Level.Error, message)

  override def info(message: String): Unit = log(Level.Info, message)

  override def warn(message: String): Unit = log(Level.Warn, message)

  override def trace(t: Throwable): Unit = out.println(StackTrace.trimmed(t, 0))

  def log(
    level: Level.Value,
    message: => String
  ): Unit = {
    if (level >= thisLevel) {
      val (colorStart, prefix) = level match {
        case Level.Debug => (CYAN, "[debug]")
        case Level.Info => (GREEN, "[info]")
        case Level.Warn => (YELLOW, "[warn]")
        case Level.Error => (RED, "[error]")
      }
      val colored = s"$colorStart$prefix $message$RESET"
      out.println(colored)
    }
  }
}

object PantsCompileMain {
  val bloopVersion = BuildInfo.version
  val bspVersion = BuildInfo.bspVersion

  // implicit lazy val scheduler: Scheduler = Scheduler.Implicits.global
  implicit lazy val scheduler: Scheduler = Scheduler(
    Executors.newFixedThreadPool(10),
    ExecutionModel.AlwaysAsyncExecution
  )

  def main(args: Array[String]): Unit = {
    val (Array(logLevelArg), compileTargets) = {
      val index = args.indexOf("--")
      if (index == -1) (args, Array.empty[String])
      else args.splitAt(index)
    }
    val logLevel = logLevelArg match {
      case "debug" => Level.Debug
      case "info" => Level.Info
      case "warn" => Level.Warn
      case "error" => Level.Error
      case x => throw new Exception(s"unrecognized log level argument '$x'")
    }

    val launcherIn = new PipedInputStream()
    val clientOut = new PipedOutputStream(launcherIn)

    val clientIn = new PipedInputStream()
    val launcherOut = new PipedOutputStream(clientIn)

    val startedServer = Promise[Unit]()

    val task = Task.fromFuture(startedServer.future).flatMap { Unit =>
      val logger = new BareBonesLogger(logLevel)
      val bspLogger = new BspClientLogger(logger)

      implicit val bspClient = new BloopLanguageClient(clientOut, bspLogger)
      val messages = BaseProtocolMessage.fromInputStream(clientIn, bspLogger)

      implicit val _ctx: DebugFilter = DebugFilter.All

      val services = Services
        .empty(bspLogger)
        .notification(endpoints.Build.showMessage) {
          case bsp.ShowMessageParams(bsp.MessageType.Log, _, _, msg) => logger.debug(msg)
          case bsp.ShowMessageParams(bsp.MessageType.Info, _, _, msg) => logger.info(msg)
          case bsp.ShowMessageParams(bsp.MessageType.Warning, _, _, msg) => logger.warn(msg)
          case bsp.ShowMessageParams(bsp.MessageType.Error, _, _, msg) => logger.error(msg)
        }.notification(endpoints.Build.logMessage) {
          case bsp.LogMessageParams(bsp.MessageType.Log, _, _, msg) => logger.debug(msg)
          case bsp.LogMessageParams(bsp.MessageType.Info, _, _, msg) => logger.info(msg)
          case bsp.LogMessageParams(bsp.MessageType.Warning, _, _, msg) => logger.warn(msg)
          case bsp.LogMessageParams(bsp.MessageType.Error, _, _, msg) => logger.error(msg)
        }.notification(endpoints.Build.publishDiagnostics) {
          case bsp.PublishDiagnosticsParams(uri, _, _, diagnostics, _) =>
            // We prepend diagnostics so that tests can check they came from this notification
            def printDiagnostic(d: bsp.Diagnostic): String = s"[diagnostic] ${d.message} ${d.range}"
            diagnostics.foreach { d =>
              d.severity match {
                case Some(bsp.DiagnosticSeverity.Error) => logger.error(printDiagnostic(d))
                case Some(bsp.DiagnosticSeverity.Warning) => () // logger.warn(printDiagnostic(d))
                case Some(bsp.DiagnosticSeverity.Information) => logger.info(printDiagnostic(d))
                case Some(bsp.DiagnosticSeverity.Hint) => logger.debug(printDiagnostic(d))
                case None => logger.info(printDiagnostic(d))
              }
            }
        }.notification(endpoints.Build.taskStart) {
          case bsp.TaskStartParams(_, _, Some(message), _, _) =>
            logger.info(s"Task started: $message")
          case _ => ()
        }.notification(endpoints.Build.taskProgress) {
          case bsp.TaskProgressParams(_, _, Some(message), Some(total), Some(progress), Some(unit), _, _) =>
            // logger.debug(s"Task progress ($progress/$total $unit): $message")
            ()
          case bsp.TaskProgressParams(_, _, Some(message), _, _, _, _, _) =>
            // logger.debug(s"Task progress: $message")
            ()
          case _ => ()
        }.notification(endpoints.Build.taskFinish) {
          case bsp.TaskFinishParams(_, _, Some(message), status, _, _) => status match {
            case bsp.StatusCode.Ok => logger.info(s"Task finished with status [$status]: $message")
            case bsp.StatusCode.Error => logger.error(s"Task finished with status [$status]: $message")
            case bsp.StatusCode.Cancelled => logger.warn(s"Task finished with status [$status]: $message")
          }
          case _ => ()
        }

      val bspServer = new BloopLanguageServer(messages, bspClient, services, scheduler, bspLogger)
      val runningClientServer = bspServer.startTask.runAsync(scheduler)

      def ack(a: Ack): Unit = a match {
        case Ack.Continue => ()
        case Ack.Stop => throw new Exception("stopped???")
      }

      def err[S](r: Either[_, S]): S = r match {
        case Left(s) => throw new Exception(s"error: $s")
        case Right(result) => result
      }

      endpoints.Build.initialize.request(bsp.InitializeBuildParams(
        displayName = "pants-bloop-client",
        version = bloopVersion,
        bspVersion = bspVersion,
        rootUri = bsp.Uri(Environment.cwd.toUri),
        capabilities = bsp.BuildClientCapabilities(List("scala", "java")),
        data = None
      )).map(err(_))
        .flatMap { result =>
          // TODO: validate or something!
          logger.info(s"initializeResult: $result")
          Task.fromFuture(endpoints.Build.initialized.notify(bsp.InitializedBuildParams()))
        }.map(ack(_))
        .flatMap { Unit =>
          endpoints.Workspace.buildTargets.request(bsp.WorkspaceBuildTargetsRequest())
        }.map(err(_))
        .map(_.targets)
        .flatMap { targets =>
          val targetIds = compileTargets.toSet
          val matchingTargets = targets.filter(_.displayName.filter(targetIds).isDefined).toList
          val mIds = matchingTargets.flatMap(_.displayName)
          logger.info(s"matchingTargets: $mIds")

          endpoints.BuildTarget.compile.request(bsp.CompileParams(
            targets = matchingTargets.map(_.id).toList,
            originId = None,
            arguments = None
          ))
        }.map(err(_))
        .map {
          case bsp.CompileResult(_, bsp.StatusCode.Ok,
            Some("project-name-classes-dir-mapping"),
            Some(mapping)) => {
            logger.info(s"mapped: $mapping")

            val outputDir = pwd / ".pants.d" / ".tmp"
            rm(outputDir)
            mkdir(outputDir)
            val nonTempDirMapping = err(mapping.as[Map[String, String]]).map {
              case (targetId, tempClassesDir) =>
                val curTargetOutputDir = outputDir / RelPath(targetId)
                logger.info(s"copying temp dir $tempClassesDir to $curTargetOutputDir!!")
                // TODO: for some reason ammonite-ops `cp` just hangs here???
                %%("cp", "-r", Path(tempClassesDir).toString, curTargetOutputDir.toString)(pwd)
                (targetId -> curTargetOutputDir.toString)
            }.toMap

            System.out.println(nonTempDirMapping.asJson)
            System.out.close()
            sys.exit(0)
            ()
          }
          case bsp.CompileResult(_, bsp.StatusCode.Ok, _, _) => {
            logger.info("(weirdly empty!!!!) compile succeeded!")
            sys.exit(0)
            ()
          }
          case x => throw new Exception(s"compile failed: $x")
        }.map { Unit => sys.exit(0) }
    }.runAsync(scheduler)

    val launcherTask = Task.eval(new LauncherMain(
      clientIn = launcherIn,
      clientOut = launcherOut,
      out = System.err,
      charset = StandardCharsets.UTF_8,
      shell = Shell.default,
      nailgunPort = None,
      startedServer = startedServer,
      generateBloopInstallerURL = Installer.defaultWebsiteURL(_)
    ).main(Array(bloopVersion))).runAsync(scheduler)
  }
}
