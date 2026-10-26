#pragma once
#include <Arduino.h>
#include "telemetry_state.h"

namespace unoq { namespace telemetry {
constexpr uint32_t LEASE_MS = 10000;
constexpr uint32_t MATRIX_INTERVAL_MS = 200;
void start(int32_t boot);
void capture(const Controller& controller, const uint8_t* requested, const int8_t* pins);
void publish();
void command(uint8_t operation, int32_t result);
String snapshot();
String health();
int32_t subscribe(String endpoint);
int32_t renew(int32_t token);
int32_t unsubscribe(int32_t token);
} }  // namespace unoq::telemetry
