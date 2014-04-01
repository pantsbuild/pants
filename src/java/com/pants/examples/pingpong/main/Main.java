// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.pingpong.main;

import java.net.InetSocketAddress;
import java.util.Arrays;

import com.google.common.collect.ImmutableMap;
import com.google.inject.AbstractModule;
import com.google.inject.Inject;
import com.google.inject.Module;
import com.google.inject.TypeLiteral;
import com.sun.jersey.api.client.Client;
import com.sun.jersey.guice.JerseyServletModule;
import com.sun.jersey.guice.spi.container.servlet.GuiceContainer;

import com.twitter.common.application.AbstractApplication;
import com.twitter.common.application.AppLauncher;
import com.twitter.common.application.Lifecycle;
import com.twitter.common.application.http.Registration;
import com.twitter.common.application.modules.HttpModule;
import com.twitter.common.application.modules.LogModule;
import com.twitter.common.application.modules.StatsModule;
import com.twitter.common.args.Arg;
import com.twitter.common.args.CmdLine;
import com.twitter.common.args.constraints.NotNull;
import com.twitter.common.base.Closure;
import com.twitter.common.examples.pingpong.handler.PingHandler;

/**
 * An application that serves HTTP requests to /ping/{message}/{ttl}, and
 * sends similar pings back to a pre-defined ping target.
 */
public class Main extends AbstractApplication {
  @NotNull
  @CmdLine(name = "ping_target", help = "Host to ping after starting up.")
  private static final Arg<InetSocketAddress> PING_TARGET = Arg.create();

  @Inject private Lifecycle lifecycle;

  @Override
  public void run() {
    lifecycle.awaitShutdown();
  }

  @Override
  public Iterable<? extends Module> getModules() {
    return Arrays.asList(
        new HttpModule(),
        new LogModule(),
        new StatsModule(),
        new AbstractModule() {
          @Override protected void configure() {
            bind(new TypeLiteral<Closure<String>>() { }).toInstance(
                new Closure<String>() {
                  private final Client http = Client.create();
                  @Override public void execute(String path) {
                    http.asyncResource("http://" + PING_TARGET.get() + path).get(String.class);
                  }
                });

            install(new JerseyServletModule() {
              @Override protected void configureServlets() {
                filter("/ping*").through(
                    GuiceContainer.class, ImmutableMap.<String, String>of());
                Registration.registerEndpoint(binder(), "/ping");
                bind(PingHandler.class);
              }
            });
          }
        }
    );
  }

  public static void main(String[] args) {
    AppLauncher.launch(Main.class, args);
  }
}
