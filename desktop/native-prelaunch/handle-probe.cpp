// Fixed synthetic diagnostic child. Not an application adapter or shipped asset.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
static void number(const char* label, unsigned long long value) {
    char row[160], digits[24]; unsigned n = 0, d = 0;
    const char* prefix = "{\"probe\":\"";
    while (*prefix) row[n++] = *prefix++;
    while (*label) row[n++] = *label++;
    const char* middle = "\",\"value\":";
    while (*middle) row[n++] = *middle++;
    do { digits[d++] = '0' + (char)(value % 10); value /= 10; } while (value);
    while (d) row[n++] = digits[--d];
    row[n++] = '}'; row[n++] = '\n'; DWORD written = 0;
    if (!WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), row, n, &written, nullptr) || written != n) ExitProcess(71);
}
static HANDLE supplied(const wchar_t* key) {
    wchar_t value[24]; DWORD n = GetEnvironmentVariableW(key, value, 24);
    if (!n || n >= 24) ExitProcess(72);
    uintptr_t handle = 0;
    for (DWORD i = 0; i < n; ++i) {
        if (value[i] < L'0' || value[i] > L'9' || handle > (UINTPTR_MAX - 9) / 10) ExitProcess(73);
        handle = handle * 10 + value[i] - L'0';
    }
    return (HANDLE)handle;
}
int main() {
    number("pid", GetCurrentProcessId());
    number("stdin_pipe", GetFileType(GetStdHandle(STD_INPUT_HANDLE)) == FILE_TYPE_PIPE);
    number("stdout_pipe", GetFileType(GetStdHandle(STD_OUTPUT_HANDLE)) == FILE_TYPE_PIPE);
    number("stderr_pipe", GetFileType(GetStdHandle(STD_ERROR_HANDLE)) == FILE_TYPE_PIPE);
    char buffer[32]{}; DWORD n = 0;
    BOOL read = ReadFile(supplied(L"DAF_GATE_READ"), buffer, sizeof(buffer), &n, nullptr);
    number("extra_read_succeeded", read != FALSE); number("extra_read_bytes", n);
    n = 0;
    BOOL write = WriteFile(supplied(L"DAF_GATE_WRITE"), "UNAUTHORIZED", 12, &n, nullptr);
    number("extra_write_succeeded", write != FALSE); number("extra_write_bytes", n);
    HANDLE mapping = supplied(L"DAF_GATE_MAPPING");
    void* view = MapViewOfFile(mapping, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, 32);
    number("extra_mapping_succeeded", view != nullptr);
    if (view) { ((volatile char*)view)[0] = '!'; UnmapViewOfFile(view); }
    number("extra_event_succeeded", SetEvent(supplied(L"DAF_GATE_EVENT")) != FALSE);
    number("extra_process_pid", GetProcessId(supplied(L"DAF_GATE_PROCESS")));
    HANDLE duplicate = nullptr;
    BOOL duplicated = DuplicateHandle(supplied(L"DAF_GATE_PROCESS"), supplied(L"DAF_GATE_READ"),
        GetCurrentProcess(), &duplicate, GENERIC_READ, FALSE, 0);
    number("extra_duplicate_succeeded", duplicated != FALSE);
    if (duplicate) CloseHandle(duplicate);
    return 0;
}
