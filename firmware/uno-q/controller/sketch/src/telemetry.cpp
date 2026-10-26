#include "telemetry.h"
#include <Arduino_RouterBridge.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <climits>
#include <cstdio>
#include <cstring>

namespace unoq { namespace telemetry {
namespace {
K_MSGQ_DEFINE(events, sizeof(StateEvent), 8, 4);
K_MUTEX_DEFINE(ownerMutex);
K_THREAD_STACK_DEFINE(publisherStack, 2048);
struct k_thread publisherThread;
atomic_t dropped = ATOMIC_INIT(0), sent = ATOMIC_INIT(0);
DeviceState current{}, published{};
uint32_t eventSequence = 0, commandCount = 0, lastMatrixMs = 0, lastErrorCommand = 0;
int32_t lastResult = 0, nextToken = 0, owner = 0;
uint8_t lastOperation = 0;
uint32_t renewedAt = 0;
char endpoint[35]{};
bool force = false;

void expireLocked(uint32_t now) {
  if (owner && uint32_t(now - renewedAt) >= LEASE_MS) {
    owner = 0;
    k_msgq_purge(&events);
  }
}

void sender(void*, void*, void*) {
  StateEvent event{};
  while (true) {
    k_msgq_get(&events, &event, K_FOREVER);
    char target[35]{};
    k_mutex_lock(&ownerMutex, K_FOREVER);
    expireLocked(millis());
    if (owner == event.token) std::memcpy(target, endpoint, sizeof(target));
    k_mutex_unlock(&ownerMutex);
    if (!target[0]) continue;
    const auto json = eventJson(event);
    if (json.empty()) { atomic_inc(&dropped); continue; }
    // No queue/owner lock is held during UART work. Notifications are best-effort.
    Bridge.notify(String(target), String(json.c_str()));
    atomic_inc(&sent);
  }
}

void enqueue(uint8_t kind, uint8_t cause, int32_t token) {
  StateEvent event{};
  current.sequence = ++eventSequence;
  event.state = current;
  event.token = token;
  event.kind = kind;
  event.cause = cause;
  event.operation = lastOperation;
  event.error = lastResult;
  if (k_msgq_put(&events, &event, K_NO_WAIT) != 0) {
    StateEvent discarded{};
    if (k_msgq_get(&events, &discarded, K_NO_WAIT) == 0) atomic_inc(&dropped);
    if (k_msgq_put(&events, &event, K_NO_WAIT) != 0) atomic_inc(&dropped);
  }
}
}  // namespace

void start(int32_t boot) {
  current.boot = boot;
  k_thread_create(&publisherThread, publisherStack, K_THREAD_STACK_SIZEOF(publisherStack),
                  sender, nullptr, nullptr, nullptr, 7, 0, K_NO_WAIT);
  k_thread_name_set(&publisherThread, "unoq-telemetry");
}

void command(uint8_t operation, int32_t result) {
  ++commandCount;
  lastOperation = operation;
  lastResult = result < 0 ? result : 0;
}

void capture(const Controller& controller, const uint8_t* requested, const int8_t* pins) {
  DeviceState next = current;
  next.milliseconds = millis();
  next.command = commandCount;
  for (int i = 0; i < 2; ++i) { next.requested[i] = requested[i]; next.pins[i] = pins[i]; }
  next.frame = controller.frame();
  next.grayscale = controller.grayscale();
  next.preset = controller.preset();
  next.playing = controller.playing();
  next.index = controller.frameIndex();
  next.count = controller.frameCount();
  next.committed = controller.committedId();
  next.upload = controller.uploadId();
  if (!sameState(next, current)) ++next.revision;
  next.sequence = eventSequence;
  current = next;
}

void publish() {
  int32_t token;
  k_mutex_lock(&ownerMutex, K_FOREVER);
  expireLocked(current.milliseconds);
  token = owner;
  k_mutex_unlock(&ownerMutex);
  if (!token) return;
  const bool matrixCommand = matrixCommandChanged(current, published, lastOperation);
  for (int i = 0; i < 2; ++i) {
    if (force || current.requested[i] != published.requested[i] || current.pins[i] != published.pins[i]) {
      enqueue(i == 0 ? RGB3 : RGB4, rgbCause(current, published, i), token);
      published.requested[i] = current.requested[i]; published.pins[i] = current.pins[i];
    }
  }
  const bool immediate = current.playing != published.playing || current.committed != published.committed ||
                         current.upload != published.upload || (matrixCommand && lastOperation != 6 && lastOperation != 12);
  if (force || (!sameMatrix(current, published) &&
      (immediate || uint32_t(current.milliseconds - lastMatrixMs) >= MATRIX_INTERVAL_MS))) {
    enqueue(MATRIX, matrixCommand ? COMMAND : PLAYBACK, token);
    // Keep independent RGB comparison state while accepting the new matrix state.
    for (int i = 0; i < 2; ++i) { published.requested[i] = current.requested[i]; published.pins[i] = current.pins[i]; }
    published.frame = current.frame; published.playing = current.playing;
    published.grayscale = current.grayscale;
    published.preset = current.preset;
    published.index = current.index; published.count = current.count;
    published.committed = current.committed; published.upload = current.upload;
    lastMatrixMs = current.milliseconds;
  }
  if (lastResult < 0 && lastErrorCommand != commandCount) {
    enqueue(ERROR, COMMAND, token);
    lastErrorCommand = commandCount;
  }
  published.command = current.command;
  force = false;
}

String snapshot() {
  current.sequence = eventSequence;
  return String(snapshotJson(current).c_str());
}

String health() {
  bool active;
  k_mutex_lock(&ownerMutex, K_FOREVER);
  expireLocked(millis()); active = owner != 0;
  k_mutex_unlock(&ownerMutex);
  char out[224];
  std::snprintf(out, sizeof(out),
    "{\"v\":1,\"b\":%ld,\"up\":%llu,\"r\":%lu,\"s\":%lu,\"c\":%lu,\"e\":%ld,\"op\":%u,\"active\":%s,\"q\":%u,\"d\":%lu,\"sent\":%lu}",
    static_cast<long>(current.boot), static_cast<unsigned long long>(k_uptime_get()),
    static_cast<unsigned long>(current.revision), static_cast<unsigned long>(eventSequence),
    static_cast<unsigned long>(commandCount), static_cast<long>(lastResult), lastOperation,
    active ? "true" : "false", k_msgq_num_used_get(&events),
    static_cast<unsigned long>(static_cast<uint32_t>(atomic_get(&dropped))),
    static_cast<unsigned long>(static_cast<uint32_t>(atomic_get(&sent))));
  return out;
}

int32_t subscribe(String name) {
  constexpr const char* prefix = "unoq.telemetry.v1.";
  if (name.length() != 34 || std::strncmp(name.c_str(), prefix, 18) != 0) return INVALID;
  for (unsigned i = 18; i < name.length(); ++i)
    if (!((name[i] >= '0' && name[i] <= '9') || (name[i] >= 'a' && name[i] <= 'f'))) return INVALID;
  k_mutex_lock(&ownerMutex, K_FOREVER);
  expireLocked(millis());
  int32_t result;
  if (owner && std::strcmp(endpoint, name.c_str()) == 0) {
    renewedAt = millis(); result = owner;  // idempotent retry after an ambiguous reply
  }
  else if (owner) result = BUSY;
  else if (nextToken == INT32_MAX) result = NO_SPACE;
  else {
    k_msgq_purge(&events);
    owner = ++nextToken; renewedAt = millis();
    std::memcpy(endpoint, name.c_str(), 34); endpoint[34] = 0;
    force = true; result = owner;
  }
  k_mutex_unlock(&ownerMutex);
  return result;
}

int32_t renew(int32_t token) {
  k_mutex_lock(&ownerMutex, K_FOREVER);
  expireLocked(millis());
  int32_t result = owner && owner == token ? OK : STALE;
  if (result == OK) renewedAt = millis();
  k_mutex_unlock(&ownerMutex);
  return result;
}

int32_t unsubscribe(int32_t token) {
  k_mutex_lock(&ownerMutex, K_FOREVER);
  expireLocked(millis());
  int32_t result = owner && owner == token ? OK : STALE;
  if (result == OK) { owner = 0; k_msgq_purge(&events); }
  k_mutex_unlock(&ownerMutex);
  return result;
}
} }  // namespace unoq::telemetry
