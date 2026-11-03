// A5 object-specific corroboration AFTER the unchanged common detector refuses.
// Only the retained, already-matched synthetic object is queried; no child code.
#pragma once
#include "suspended-inspection.h"
#include "handle-diagnostic.h"
namespace a5 {
struct Case { const wchar_t* name; unsigned number, reference; bool alias; };
inline constexpr Case Cases[] = {
    {L"A5-03", 3, 1, false}, {L"A5-04", 4, 2, false},
    {L"A5-05", 5, 3, false}, {L"A5-06", 6, 4, false},
    {L"A5-08", 8, 1, true}, {L"A5-09", 9, 2, true},
    {L"A5-10", 10, 3, true}, {L"A5-11", 11, 4, true},
};
inline unsigned caseNumber = 0, referenceIndex = 0, sequence = 0;
inline bool aliasCase = false;
inline uintptr_t originalValue = 0, inheritedValue = 0;
inline FILE_ID_INFO originalId{};
inline std::wstring backingName;
inline DWORD hostPid = 0;
inline ULONGLONG hostCreation = 0;
inline bool select(const std::wstring& name) {
    for (unsigned i = 0; i < 8; ++i) if (name == Cases[i].name) {
        sequence = i + 1; caseNumber = Cases[i].number;
        referenceIndex = Cases[i].reference; aliasCase = Cases[i].alias; return true;
    }
    return false;
}
inline thread_local a3::State* typeState = nullptr;
inline void typeEvent(unsigned, const char* key, unsigned long long value) {
    typeState->put(std::string("fixture_") + key, value);
}
inline void fileWitness(a3::State& s, HANDLE copy) {
    FILE_ID_INFO file{}; BY_HANDLE_FILE_INFORMATION basic{};
    BOOL id = GetFileInformationByHandleEx(copy, FileIdInfo, &file, sizeof(file));
    s.put("fixture_file_id_ok", id != FALSE); s.put("fixture_file_id_error", id ? 0 : GetLastError());
    s.require(id, 221);
    unsigned long long halves[2]{}; memcpy(halves, file.FileId.Identifier, sizeof(halves));
    s.put("fixture_volume", file.VolumeSerialNumber);
    s.put("fixture_file_low", halves[0]); s.put("fixture_file_high", halves[1]);
    s.require(prelaunch::equal(file, originalId), 222);
    BOOL regular = GetFileInformationByHandle(copy, &basic);
    bool expected = regular && !(basic.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) &&
        basic.nNumberOfLinks == 1 && !basic.nFileSizeHigh && basic.nFileSizeLow == 32;
    s.put("fixture_file_regular_32", expected); s.require(expected, 223);
}
struct View {
    void* address = nullptr;
    ~View() { if (address) UnmapViewOfFile(address); }
};
inline void mappingWitness(a3::State& s, HANDLE copy) {
    View view; view.address = MapViewOfFile(copy, FILE_MAP_READ, 0, 0, 32);
    s.put("fixture_map_ok", view.address != nullptr);
    s.put("fixture_map_error", view.address ? 0 : GetLastError());
    s.require(view.address != nullptr, 224);
    // Metadata of this exact 32-byte synthetic view only. No mapped bytes read.
    MEMORY_BASIC_INFORMATION info{};
    SIZE_T bytes = VirtualQuery(view.address, &info, sizeof(info));
    s.put("fixture_map_query_bytes", bytes); s.put("fixture_map_type", info.Type);
    s.put("fixture_map_state", info.State); s.put("fixture_map_protection", info.Protect);
    s.put("fixture_map_region_bytes", info.RegionSize);
    s.require(bytes == sizeof(info) && info.Type == MEM_MAPPED && info.State == MEM_COMMIT &&
        info.Protect == PAGE_READONLY && info.RegionSize >= 32 && info.RegionSize <= 65536, 225);
    wchar_t mapped[32768]{};
    DWORD length = GetMappedFileNameW(GetCurrentProcess(), view.address, mapped, 32768);
    s.put("fixture_map_name_ok", length > 0 && length < 32768);
    s.put("fixture_map_name_error", length ? 0 : GetLastError());
    bool sameBacking = length && length < 32768 && std::wstring(mapped, length) == backingName;
    s.put("fixture_map_backing_match", sameBacking); s.require(sameBacking, 226);
    BOOL unmapped = UnmapViewOfFile(view.address);
    s.put("fixture_map_unmap_ok", unmapped != FALSE);
    s.put("fixture_map_unmap_error", unmapped ? 0 : GetLastError());
    if (unmapped) view.address = nullptr;
    s.require(unmapped != FALSE, 227);
}
inline void eventWitness(a3::State& s, HANDLE copy) {
    DWORD observed = WaitForSingleObject(copy, 0);
    s.put("fixture_event_wait", observed);
    s.require(observed == WAIT_TIMEOUT, 228); // Read-only state, never signal/reset here.
}
inline void processWitness(a3::State& s, HANDLE copy) {
    DWORD pid = GetProcessId(copy); DWORD error = pid ? 0 : GetLastError();
    s.put("fixture_process_pid", pid); s.put("fixture_process_pid_error", error);
    FILETIME created{}, exited{}, kernel{}, user{};
    BOOL times = GetProcessTimes(copy, &created, &exited, &kernel, &user);
    s.put("fixture_process_times_ok", times != FALSE);
    s.put("fixture_process_times_error", times ? 0 : GetLastError());
    s.put("fixture_process_creation", a3::timeValue(created));
    DWORD code = 0; BOOL queried = GetExitCodeProcess(copy, &code);
    s.put("fixture_process_exit_ok", queried != FALSE); s.put("fixture_process_exit", code);
    s.require(pid == hostPid && pid == GetCurrentProcessId() && pid != s.pid &&
        times && a3::timeValue(created) == hostCreation && queried && code == STILL_ACTIVE, 229);
}
inline void objectWitness(a3::State& s, HANDLE copy) {
    typeState = &s;
    DWORD kind = hd::type(copy, referenceIndex, typeEvent);
    typeState = nullptr;
    s.put("fixture_type", kind);
    // Type corroborates, never replaces the preceding kernel-object comparison.
    s.require(kind == referenceIndex, 230);
    if (referenceIndex == 1) fileWitness(s, copy);
    else if (referenceIndex == 2) mappingWitness(s, copy);
    else if (referenceIndex == 3) eventWitness(s, copy);
    else if (referenceIndex == 4) processWitness(s, copy);
    else s.require(false, 231);
}
} // namespace a5
