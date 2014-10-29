#!/bin/bash

OUTPUT_DIR=.pants.d/gen/wire/gen-java/

mkdir -p ${OUTPUT_DIR}

java -jar ~/Src/wire/wire-compiler/target/wire-compiler-1.5.3-SNAPSHOT-jar-with-dependencies.jar \
--proto_path=/Users/arp/Src/pants \
--java_out=/Users/arp/Src/pants/.pants.d/gen/wire/gen-java \
--service_writer="com.squareup.wire.SimpleServiceWriter" \
--roots=com.pants.examples.temperature.TemperatureService#GetTemperature \
--roots=com.pants.examples.temperature.TemperatureService#PredictTemperature \
examples/src/wire/com/pants/examples/temperature/temperatures.proto


