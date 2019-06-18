package pants.contrib.bloop.compile

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
    Executors.newFixedThreadPool(4),
    ExecutionModel.AlwaysAsyncExecution
  )

  def main(args: Array[String]): Unit = {
    val launcherIn = new PipedInputStream()
    val clientOut = new PipedOutputStream(launcherIn)

    val clientIn = new PipedInputStream()
    val launcherOut = new PipedOutputStream(clientIn)

    val startedServer = Promise[Unit]()

    val task = startedServer.future.flatMap { Unit =>
      // TODO: set this level from somewhere!
      val logger = new BareBonesLogger(Level.Debug)
      val bspLogger = new BspClientLogger(logger)

      implicit val bspClient = new BloopLanguageClient(clientOut, bspLogger)
      val messages = BaseProtocolMessage.fromInputStream(clientIn, bspLogger)

      val services = Services.empty(bspLogger)

      val bspServer = new BloopLanguageServer(messages, bspClient, services, scheduler, bspLogger)
      val runningClientServer = bspServer.startTask.runAsync(scheduler)

      val initializeBuildParams = bsp.InitializeBuildParams(
        displayName = "pants-bloop-client",
        version = bloopVersion,
        bspVersion = bspVersion,
        rootUri = bsp.Uri(Environment.cwd.toUri),
        capabilities = bsp.BuildClientCapabilities(List("scala")),
        data = None
      )

      throw new Exception(s"initializeBuildParams: $initializeBuildParams")

      endpoints.Build.initialize.request(initializeBuildParams)
        .flatMap { initializeResult =>
          println(s"initializeResult: $initializeResult")
          throw new Exception(s"initializeResult: $initializeResult")
          // TODO: validate or something!
          Task.fromFuture(endpoints.Build.initialized.notify(bsp.InitializedBuildParams()))
        }.map {
          case Ack.Continue => throw new Exception("wow!!")
          case Ack.Stop => throw new Exception("stopped???")
        }.runAsync(scheduler)
    }

    new LauncherMain(
      clientIn = launcherIn,
      clientOut = launcherOut,
      out = System.err,
      charset = StandardCharsets.UTF_8,
      shell = Shell.default,
      nailgunPort = None,
      startedServer = startedServer,
      generateBloopInstallerURL = Installer.defaultWebsiteURL(_)
    ).main(args :+ bloopVersion)

    Await.result(task, FiniteDuration(2, "s"))
  }
}
