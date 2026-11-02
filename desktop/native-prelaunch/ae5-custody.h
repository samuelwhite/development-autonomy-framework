// Diagnostic-only A-E5. Both source release gates remain closed.
#pragma once
#include "identity.h"
#include "suspended-inspection.h"
#include <aclapi.h>
#include <stdexcept>
#include <string>
#include <iostream>
namespace ae5 {
// Volatile read retains dormant code for compiler/import review. Read-only source
// constant, not a command-line, environment, IPC or exported activation switch.
inline volatile const LONG NativeRelease = 0;
inline bool nativeReleased() { return NativeRelease == 1; }
struct Ack {
    DWORD magic, sequence;
    unsigned long long deadline, parentPid, parentCreation;
    char exercise[32];
};
static_assert(sizeof(Ack) == 64, "closed acknowledgement size");
inline Ack initial{};
inline DWORD sequence = 0;
inline HANDLE incoming = nullptr, outgoing = nullptr;
inline bool initialized = false;
inline void need(bool ok) { if (!ok) throw std::runtime_error("A-E5 custody refused"); }
inline std::string number(unsigned long long value) { return std::to_string(value); }
inline std::string quote(const std::wstring& input) {
    need(input.size() <= 2048);
    int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, input.data(), (int)input.size(), nullptr, 0, nullptr, nullptr);
    need(size >= 0 && size <= 8192);
    std::string utf(size, '\0');
    need(WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, input.data(), (int)input.size(), utf.data(), size, nullptr, nullptr) == size);
    std::string result = "\"";
    for (unsigned char ch : utf) {
        need(ch >= 32);
        if (ch == '"' || ch == '\\') result += '\\';
        result += static_cast<char>(ch);
    }
    return result + "\"";
}
inline unsigned long long creation(HANDLE process) {
    FILETIME c{}, e{}, k{}, u{};
    need(GetProcessTimes(process, &c, &e, &k, &u));
    return ((unsigned long long)c.dwHighDateTime << 32) | c.dwLowDateTime;
}
inline void readExact(void* value, DWORD size) {
    DWORD offset = 0;
    while (offset < size) {
        DWORD got = 0;
        need(ReadFile(incoming, (BYTE*)value + offset, size - offset, &got, nullptr) && got != 0);
        offset += got;
    }
}
inline void receive(DWORD expected) {
    Ack value{}; readExact(&value, sizeof(value));
    need(value.magic == 0x35454144 && value.sequence == expected && value.parentPid != 0);
    for (char c : value.exercise) need((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'));
    need(GetTickCount64() < value.deadline);
    if (initialized) {
        need(value.parentPid == initial.parentPid && value.parentCreation == initial.parentCreation &&
            memcmp(value.exercise, initial.exercise, 32) == 0 && value.deadline <= initial.deadline);
    } else { initial = value; initialized = true; }
}
inline void initialize() {
    need(nativeReleased());
    incoming = GetStdHandle(STD_INPUT_HANDLE); outgoing = GetStdHandle(STD_OUTPUT_HANDLE);
    need(GetFileType(incoming) == FILE_TYPE_PIPE && GetFileType(outgoing) == FILE_TYPE_PIPE);
    need(SetHandleInformation(incoming, HANDLE_FLAG_INHERIT, 0));
    need(SetHandleInformation(outgoing, HANDLE_FLAG_INHERIT, 0));
    receive(0);
}
inline void rpc(const char* kind, const std::string& data) {
    need(initialized && sequence < 256 && GetTickCount64() < initial.deadline);
    const auto message = "{\"v\":1,\"exercise\":\"" + std::string(initial.exercise, 32) +
        "\",\"seq\":" + number(++sequence) + ",\"kind\":\"" + kind + "\",\"data\":" + data + "}";
    need(message.size() <= 32768);
    DWORD length = (DWORD)message.size(), written = 0;
    need(WriteFile(outgoing, &length, sizeof(length), &written, nullptr) && written == sizeof(length));
    need(WriteFile(outgoing, message.data(), length, &written, nullptr) && written == length);
    receive(sequence);
}
inline std::string descriptor(PSECURITY_DESCRIPTOR sd) {
    SECURITY_DESCRIPTOR_CONTROL control{}; DWORD revision = 0;
    need(sd && IsValidSecurityDescriptor(sd) && GetSecurityDescriptorControl(sd, &control, &revision) &&
        (control & SE_SELF_RELATIVE));
    DWORD bytes = GetSecurityDescriptorLength(sd); need(bytes > 0 && bytes <= 8192);
    const char digits[] = "0123456789abcdef"; std::string result;
    for (DWORD i = 0; i < bytes; ++i) {
        BYTE ch = ((BYTE*)sd)[i]; result += digits[ch >> 4]; result += digits[ch & 15];
    }
    return result;
}
inline void intent(const char* kind, const std::wstring& name, HANDLE handle = nullptr,
    unsigned object = 0, unsigned information = 0, PSECURITY_DESCRIPTOR sd = nullptr) {
    rpc("intent", "{\"kind\":\"" + std::string(kind) + "\",\"name\":" + quote(name) +
        ",\"handle\":" + number((uintptr_t)handle) + ",\"object\":" + number(object) +
        ",\"information\":" + number(information) + ",\"original\":\"" + (sd ? descriptor(sd) : "") + "\"}");
}
inline void commit(bool ok, bool created = false) {
    rpc("commit", std::string("{\"ok\":") + (ok ? "true" : "false") + ",\"created\":" + (created ? "true" : "false") + "}");
}
inline HANDLE aclBegin(const std::wstring& path, DWORD information = DACL_SECURITY_INFORMATION) {
    HANDLE handle = CreateFileW(path.c_str(), READ_CONTROL | WRITE_DAC,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    need(handle != INVALID_HANDLE_VALUE);
    PSECURITY_DESCRIPTOR sd = nullptr;
    need(GetSecurityInfo(handle, SE_FILE_OBJECT, information, nullptr, nullptr, nullptr, nullptr, &sd) == ERROR_SUCCESS);
    try { intent("acl", path, handle, SE_FILE_OBJECT, information, sd); }
    catch (...) { LocalFree(sd); CloseHandle(handle); throw; }
    LocalFree(sd); return handle;
}
inline void aclEnd(HANDLE handle) { commit(true); need(CloseHandle(handle)); }
inline void verifyParent(HANDLE handle) {
    need(GetProcessId(handle) == initial.parentPid && creation(handle) == initial.parentCreation &&
        WaitForSingleObject(handle, 0) == WAIT_TIMEOUT);
}
[[noreturn]] inline void beforeResume(HANDLE process, HANDLE thread, HANDLE job) {
    rpc("custody", "{\"process\":" + number((uintptr_t)process) + ",\"thread\":" + number((uintptr_t)thread) +
        ",\"job\":" + number((uintptr_t)job) + ",\"pid\":" + number(GetProcessId(process)) +
        ",\"tid\":" + number(GetThreadId(thread)) + ",\"creation\":" + number(creation(process)) +
        ",\"helper_creation\":" + number(creation(GetCurrentProcess())) + "}");
    // Original supervisor always terminates; original acceptance predicate unchanged.
    a3::beforeResume(process, thread, job);
    throw std::runtime_error("unexpected inspector return");
}
[[noreturn]] inline DWORD neverResume(HANDLE) { throw std::runtime_error("resume forbidden"); }
inline void cleanup(HANDLE process) {
    if (!process) throw std::runtime_error("incomplete setup: parent recovery required");
    need(WaitForSingleObject(process, 0) == WAIT_OBJECT_0);
    rpc("cleanup", "{\"child_exit\":true}");
}
} // namespace ae5
