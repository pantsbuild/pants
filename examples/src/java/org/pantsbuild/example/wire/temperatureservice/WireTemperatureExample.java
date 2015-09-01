// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.wire.temperatureservice;

import java.io.IOException;
import org.pantsbuild.example.temperature.Temperature;
import org.pantsbuild.example.temperature.TemperatureRequest;
import org.pantsbuild.example.temperature.TemperatureService;

/**
 * Simple example of creating a message with Wire and printing out its contents.
 */
class WireTemperatureExample implements TemperatureService {

  public Temperature getTemperature(TemperatureRequest request) {
    return new Temperature.Builder().unit("celsius").number(19L).build();
  }

  public Temperature predictTemperature(TemperatureRequest request) {
    return new Temperature.Builder().unit("fahrenheit").number(82L).build();
  }

  private WireTemperatureExample() {
  }

  public static void main(String[] args) throws IOException {
    // You would probably add this service definition to your favorite RPC library...
    TemperatureService service = new WireTemperatureExample();
    Temperature temp = service.getTemperature(new TemperatureRequest.Builder().build());
    System.out.println(temp.number + " degrees " + temp.unit);
  }
}
