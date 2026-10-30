// Diagnostic child only. No task adapter, arbitrary command or execution API.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static void line(const char* text) {
    DWORD n = 0, written = 0;
    while (text[n]) ++n;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), text, n, &written, 0);
}
static void number(const char* name, DWORD value) {
    char digits[16]; DWORD i = 0;
    line("{\"probe\":\""); line(name); line("\",\"value\":");
    do { digits[i++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (i) { char c[2]; c[0] = digits[--i]; c[1] = 0; line(c); }
    line("}\n");
}
static DWORD file_test(const wchar_t* leaf, DWORD access, const char* label, BOOL write) {
    wchar_t path[1024]; DWORD n = GetEnvironmentVariableW(L"DAF_ROOT", path, 900);
    if (!n || n >= 900) return 87;
    path[n++] = L'\\'; while (*leaf) path[n++] = *leaf++; path[n] = 0;
    HANDLE file = CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, 0,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    DWORD code = file == INVALID_HANDLE_VALUE ? GetLastError() : 0, count = 0;
    if (file != INVALID_HANDLE_VALUE) {
        char buffer[64];
        BOOL ok = write ? WriteFile(file, "NATIVE PROBE\n", 13, &count, 0) : ReadFile(file, buffer, sizeof(buffer), &count, 0);
        if (!ok) code = GetLastError();
        CloseHandle(file);
    }
    number(label, code); return code;
}
static DWORD probe(void) {
    line("{\"probe\":\"native_entry\",\"status\":\"observed\"}\n");
    number("pid", GetCurrentProcessId());
    if (file_test(L"dual-grant.txt", FILE_APPEND_DATA, "permitted_write_error", TRUE)) return 2;
    if (file_test(L"ambient-shared.txt", FILE_APPEND_DATA, "ambient_write_error", TRUE) != 5) {
        line("{\"probe\":\"BLOCKING_ambient_write\",\"status\":\"failure\"}\n"); return 3;
    }
    // Report ambient reads separately from write denial. No strict read claim.
    file_test(L"ambient-shared.txt", FILE_READ_DATA, "ambient_read_error", FALSE);
    if (file_test(L"allowed.txt", FILE_READ_DATA, "permitted_read_error", FALSE)) return 4;
    line("{\"probe\":\"native_basic_complete\",\"status\":\"observed\"}\n");
    return 0;
}
#ifdef STATIC_CRT
#include "native-suite.h"
int main(void) { DWORD code=probe(); return code?(int)code:fullSuite(); }
#else
void probeEntry(void) { ExitProcess(probe()); }
#endif
