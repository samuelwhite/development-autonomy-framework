// Fixed synthetic diagnostic child. No application adapter or shipped asset.
#define WIN32_LEAN_AND_MEAN
#include "handle-diagnostic.h"
static void number(const char* label, unsigned long long value) {
    char row[192], digits[24]; unsigned n = 0, d = 0;
    const char* prefix = "{\"probe\":\"";
    while (*prefix) row[n++] = *prefix++;
    while (*label) { if (n >= 144) ExitProcess(70); row[n++] = *label++; }
    const char* middle = "\",\"value\":";
    while (*middle) row[n++] = *middle++;
    do { digits[d++] = '0' + (char)(value % 10); value /= 10; } while (value);
    while (d) row[n++] = digits[--d];
    row[n++] = '}'; row[n++] = '\n'; DWORD written = 0;
    if (!WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), row, n, &written, nullptr) || written != n) ExitProcess(71);
}
static void emit(unsigned i, const char* field, unsigned long long value) {
    char key[96] = "h0_"; key[1] += (char)i; unsigned n = 3;
    while (*field && n < sizeof(key) - 1) key[n++] = *field++;
    key[n] = 0; number(key, value);
}
static ULONGLONG supplied(const wchar_t* key) {
    wchar_t value[24]; DWORD n = GetEnvironmentVariableW(key, value, 24);
    if (!n || n >= 24) ExitProcess(72);
    ULONGLONG result = 0;
    for (DWORD i = 0; i < n; ++i) {
        if (value[i] < L'0' || value[i] > L'9' || result > (UINT64_MAX - (value[i] - L'0')) / 10) ExitProcess(73);
        result = result * 10 + value[i] - L'0';
    }
    return result;
}
static FILE_ID_INFO file(const wchar_t* prefix) {
    wchar_t key[64]{}; unsigned n = 0;
    while (prefix[n]) { key[n] = prefix[n]; ++n; }
    const wchar_t* suffix[]{L"_VOLUME", L"_LOW", L"_HIGH"}; ULONGLONG values[3]{};
    for (unsigned i = 0; i < 3; ++i) {
        unsigned j = n; const wchar_t* s = suffix[i];
        while (*s) key[j++] = *s++; key[j] = 0;
        values[i] = supplied(key);
    }
    FILE_ID_INFO id{}; id.VolumeSerialNumber = values[0];
    memcpy(id.FileId.Identifier, &values[1], 8); memcpy(id.FileId.Identifier + 8, &values[2], 8);
    return id;
}
int main() {
    number("schema", 2); number("pid", GetCurrentProcessId());
    number("stdin_raw", (uintptr_t)GetStdHandle(STD_INPUT_HANDLE));
    number("stdout_raw", (uintptr_t)GetStdHandle(STD_OUTPUT_HANDLE));
    number("stderr_raw", (uintptr_t)GetStdHandle(STD_ERROR_HANDLE));
    number("stdin_pipe", GetFileType(GetStdHandle(STD_INPUT_HANDLE)) == FILE_TYPE_PIPE);
    number("stdout_pipe", GetFileType(GetStdHandle(STD_OUTPUT_HANDLE)) == FILE_TYPE_PIPE);
    number("stderr_pipe", GetFileType(GetStdHandle(STD_ERROR_HANDLE)) == FILE_TYPE_PIPE);
    const wchar_t* keys[]{L"DAF_GATE_READ", L"DAF_GATE_WRITE", L"DAF_GATE_MAPPING", L"DAF_GATE_EVENT", L"DAF_GATE_PROCESS"};
    HANDLE handles[5]{};
    for (unsigned i = 0; i < 5; ++i) { handles[i] = (HANDLE)(uintptr_t)supplied(keys[i]); emit(i, "binding", (uintptr_t)handles[i]); }
    hd::Expected expected{}; expected.read = file(L"DAF_GATE_READ_ID"); expected.write = file(L"DAF_GATE_WRITE_ID");
    expected.hostPid = (DWORD)supplied(L"DAF_GATE_HOST_PID");
    expected.hostCreation = supplied(L"DAF_GATE_HOST_CREATION"); expected.readHandle = handles[0];
    number("bindings_complete", 1);
    bool inconclusive = false, access = false;
    for (unsigned i = 0; i < 5; ++i) {
        auto result = hd::inspect(i, handles[i], expected, nullptr, emit);
        access = access || result.outcome == hd::Access || result.outcome == hd::Denied;
        inconclusive = inconclusive || (result.outcome != hd::Absent && result.outcome != hd::StandardPipe);
    }
    number("probe_complete", 1);
    return access ? 81 : inconclusive ? 82 : 0;
}
