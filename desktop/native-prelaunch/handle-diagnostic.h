// Diagnostic only. Never perform file I/O on an unidentified numeric handle.
#pragma once
#include <windows.h>
#include <winternl.h>
#include <stdint.h>
#include <cstring>
#pragma comment(lib, "onecore.lib") // SDK import for CompareObjectHandles; diagnostics only.
namespace hd {
using Emit = void (*)(unsigned, const char*, unsigned long long);
enum Kind { Read = 0, Write = 1, Mapping = 2, Event = 3, Process = 4 };
enum Outcome { Incomplete = 0, Absent = 1, StandardPipe = 2, Access = 3,
    Denied = 4, Ambiguous = 5, QueryFailed = 6 };
enum Type { Unknown = 0, File = 1, Section = 2, EventObject = 3, ProcessObject = 4, Other = 5 };
struct Expected {
    FILE_ID_INFO read{}, write{};
    DWORD hostPid = 0;
    ULONGLONG hostCreation = 0;
    HANDLE readHandle = nullptr;
};
struct Result { DWORD outcome = Incomplete, attempted = 0, ok = 0, error = 0, bytes = 0; };
inline ULONGLONG filetime(FILETIME f) { return ((ULONGLONG)f.dwHighDateTime << 32) | f.dwLowDateTime; }
inline bool sameFile(const FILE_ID_INFO& a, const FILE_ID_INFO& b) {
    return a.VolumeSerialNumber == b.VolumeSerialNumber && !memcmp(a.FileId.Identifier, b.FileId.Identifier, 16);
}
inline void fileFields(unsigned i, const FILE_ID_INFO& id, Emit emit) {
    ULONGLONG low = 0, high = 0;
    memcpy(&low, id.FileId.Identifier, 8); memcpy(&high, id.FileId.Identifier + 8, 8);
    emit(i, "volume", id.VolumeSerialNumber); emit(i, "file_low", low); emit(i, "file_high", high);
}
inline DWORD type(HANDLE h, unsigned i, Emit emit) {
    // Type only: never query an unknown object's potentially blocking name.
    auto query = (NTSTATUS(NTAPI*)(HANDLE, OBJECT_INFORMATION_CLASS, PVOID, ULONG, PULONG))
        GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryObject");
    if (!query) { emit(i, "type_status", 0xffffffff); return Unknown; }
    alignas(void*) unsigned char data[1024]{}; ULONG returned = 0;
    NTSTATUS status = query(h, ObjectTypeInformation, data, sizeof(data), &returned);
    emit(i, "type_status", (DWORD)status);
    if (status < 0 || returned > sizeof(data)) return Unknown;
    auto s = ((PUBLIC_OBJECT_TYPE_INFORMATION*)data)->TypeName;
    auto begin = (uintptr_t)s.Buffer, end = begin + s.Length;
    if (s.Length % sizeof(wchar_t) || begin < (uintptr_t)data || end < begin ||
        end > (uintptr_t)data + sizeof(data)) return Unknown;
    const wchar_t* names[]{L"", L"File", L"Section", L"Event", L"Process"};
    for (DWORD n = 1; n <= 4; ++n)
        if (s.Length == wcslen(names[n]) * sizeof(wchar_t) && !memcmp(s.Buffer, names[n], s.Length)) return n;
    return Other;
}
inline Result inspect(unsigned i, HANDLE raw, const Expected& expected, HANDLE knownReference, Emit emit) {
    Result r{};
    emit(i, "begin", 1); emit(i, "raw", (uintptr_t)raw);
    DWORD flags = 0; BOOL info = GetHandleInformation(raw, &flags);
    DWORD infoError = info ? 0 : GetLastError();
    emit(i, "info_ok", info != FALSE); emit(i, "info_error", infoError); emit(i, "flags", flags);
    // Retain an already-existing local object. Never duplicate into the child.
    emit(i, "before_duplicate", 1);
    HANDLE h = nullptr;
    BOOL copied = DuplicateHandle(GetCurrentProcess(), raw, GetCurrentProcess(), &h, 0, FALSE, DUPLICATE_SAME_ACCESS);
    DWORD copyError = copied ? 0 : GetLastError();
    emit(i, "duplicate_ok", copied != FALSE); emit(i, "duplicate_error", copyError);
    if (!copied) {
        r.outcome = !info && infoError == ERROR_INVALID_HANDLE && copyError == ERROR_INVALID_HANDLE
            ? Absent : QueryFailed;
    } else {
        emit(i, "before_metadata", 1);
        const DWORD objectType = type(h, i, emit); emit(i, "type", objectType);
        SetLastError(0); DWORD fileType = GetFileType(h);
        DWORD fileError = fileType == FILE_TYPE_UNKNOWN ? GetLastError() : 0;
        emit(i, "file_type", fileType); emit(i, "file_type_error", fileError);
        DWORD standard = 0;
        HANDLE streams[]{GetStdHandle(STD_INPUT_HANDLE), GetStdHandle(STD_OUTPUT_HANDLE), GetStdHandle(STD_ERROR_HANDLE)};
        for (unsigned n = 0; n < 3; ++n) if (CompareObjectHandles(h, streams[n])) standard |= 1u << n;
        emit(i, "standard_mask", standard);
        const bool reference = knownReference && CompareObjectHandles(h, knownReference);
        emit(i, "known_reference", reference);
        bool identity = false;
        if (i <= Write && objectType == File && fileType == FILE_TYPE_DISK) {
            FILE_ID_INFO actual{}; BY_HANDLE_FILE_INFORMATION basic{};
            BOOL idOK = GetFileInformationByHandleEx(h, FileIdInfo, &actual, sizeof(actual));
            DWORD idError = idOK ? 0 : GetLastError();
            emit(i, "id_ok", idOK != FALSE); emit(i, "id_error", idError);
            if (idOK) fileFields(i, actual, emit);
            BOOL basicOK = GetFileInformationByHandle(h, &basic);
            bool regular = basicOK && !(basic.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) &&
                basic.nNumberOfLinks == 1 && !basic.nFileSizeHigh && basic.nFileSizeLow == 32;
            emit(i, "regular_32_bytes", regular);
            identity = idOK && regular && sameFile(actual, i == Read ? expected.read : expected.write);
        } else if (i == Mapping) identity = objectType == Section && reference;
        else if (i == Event) identity = objectType == EventObject && reference;
        else if (i == Process && objectType == ProcessObject) {
            DWORD pid = GetProcessId(h); DWORD pidError = pid ? 0 : GetLastError();
            emit(i, "process_pid", pid); emit(i, "process_pid_error", pidError);
            FILETIME creation{}, exit{}, kernel{}, user{};
            BOOL times = GetProcessTimes(h, &creation, &exit, &kernel, &user);
            DWORD timeError = times ? 0 : GetLastError();
            emit(i, "process_times_ok", times != FALSE); emit(i, "process_times_error", timeError);
            emit(i, "process_creation", filetime(creation));
            identity = pid == expected.hostPid && times && filetime(creation) == expected.hostCreation;
        }
        emit(i, "intended_identity", identity);
        if (!info || objectType == Unknown) r.outcome = QueryFailed;
        else if (standard && objectType == File && fileType == FILE_TYPE_PIPE && !identity) r.outcome = StandardPipe;
        else if (!identity) r.outcome = Ambiguous;
        else {
            emit(i, "before_operation", 1); r.attempted = 1;
            if (i <= Write) {
                LARGE_INTEGER zero{}; BOOL seek = SetFilePointerEx(h, zero, nullptr, FILE_BEGIN);
                r.error = seek ? 0 : GetLastError();
                if (seek) {
                    char data[32]{}; DWORD count = 0;
                    BOOL ok = i == Read ? ReadFile(h, data, sizeof(data), &count, nullptr) : WriteFile(h, "!", 1, &count, nullptr);
                    r.error = ok ? 0 : GetLastError(); r.ok = ok != FALSE; r.bytes = count;
                    bool marker = count == sizeof(data);
                    for (char b : data) marker = marker && b == 'R';
                    if (i == Read) emit(i, "read_marker", marker);
                }
            } else if (i == Mapping) {
                void* view = MapViewOfFile(h, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, 32);
                r.error = view ? 0 : GetLastError(); r.ok = view != nullptr;
                if (view) {
                    ((volatile char*)view)[1] = 'M'; r.bytes = 1;
                    BOOL flushed = FlushViewOfFile(view, 32); DWORD flushError = flushed ? 0 : GetLastError();
                    emit(i, "mapping_flush_ok", flushed != FALSE); emit(i, "mapping_flush_error", flushError);
                    BOOL unmapped = UnmapViewOfFile(view); emit(i, "mapping_unmap_ok", unmapped != FALSE);
                    if (!flushed || !unmapped) r.ok = 0;
                }
            } else if (i == Event) {
                BOOL ok = SetEvent(h); r.error = ok ? 0 : GetLastError(); r.ok = ok != FALSE;
            } else {
                HANDLE duplicate = nullptr;
                BOOL ok = DuplicateHandle(h, expected.readHandle, GetCurrentProcess(), &duplicate, GENERIC_READ, FALSE, 0);
                r.error = ok ? 0 : GetLastError(); r.ok = ok != FALSE;
                if (ok) {
                    FILE_ID_INFO actual{};
                    BOOL identified = GetFileInformationByHandleEx(duplicate, FileIdInfo, &actual, sizeof(actual));
                    emit(i, "duplicated_read_identity", identified && sameFile(actual, expected.read));
                    if (!identified || !sameFile(actual, expected.read)) r.ok = 0;
                    if (r.ok) {
                        LARGE_INTEGER zero{}; char data[32]{}; DWORD count = 0;
                        BOOL read = SetFilePointerEx(duplicate, zero, nullptr, FILE_BEGIN) &&
                            ReadFile(duplicate, data, sizeof(data), &count, nullptr);
                        DWORD readError = read ? 0 : GetLastError();
                        bool marker = read && count == sizeof(data);
                        for (char b : data) marker = marker && b == 'R';
                        emit(i, "duplicated_read_error", readError); emit(i, "duplicated_read_marker", marker);
                        if (!marker) r.ok = 0;
                    }
                    CloseHandle(duplicate);
                }
            }
            r.outcome = r.ok ? Access : Denied;
        }
        CloseHandle(h);
    }
    emit(i, "operation_attempted", r.attempted); emit(i, "operation_ok", r.ok);
    emit(i, "operation_error", r.error); emit(i, "operation_bytes", r.bytes);
    emit(i, "outcome", r.outcome); emit(i, "complete", 1);
    return r;
}
} // namespace hd
