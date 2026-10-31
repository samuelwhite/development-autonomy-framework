// Diagnostic harness framing only. Never included by producer or verifier.
#pragma once
#include <stddef.h>
#include <string.h>
static bool readyRecord(const char* bytes, size_t size) {
    static const char expected[] = "{\"probe\":\"hold_ready\",\"status\":\"observed\",\"code\":0}";
    if (!size || bytes[size - 1] != '\n') return false;
    --size;
    if (size && bytes[size - 1] == '\r') --size;
    return size == sizeof(expected) - 1 && memcmp(bytes, expected, size) == 0;
}
static bool scanReady(const char* bytes, size_t size, size_t& cursor) {
    // Keep an incomplete tail until a later pipe read supplies its delimiter.
    for (size_t end = cursor; end < size; ++end) {
        if (bytes[end] == '\n') {
            bool ready = readyRecord(bytes + cursor, end + 1 - cursor);
            cursor = end + 1;
            if (ready) return true;
        }
    }
    return false;
}
