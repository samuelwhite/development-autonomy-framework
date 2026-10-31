// A4 diagnostic-only fixture launcher. Never used by the normal candidate or desktop.
#include "identity.h"
#include "handle-diagnostic.h"
#include "fixture-inspection.h"
#include <iostream>
#include <fstream>
#include "probe-identity.h"
namespace pg = prelaunch;
static std::unique_ptr<pg::ImagePin> imagePin;
static std::vector<std::unique_ptr<pg::Handle>> hostile;
static HANDLE diagnosticHandles[5]{}, permittedHandles[3]{};
static DWORD attributeMask = 0, attributeCount = 0;
static HANDLE fixtureHandles[4]{};
static LPPROC_THREAD_ATTRIBUTE_LIST fixtureAttributes = nullptr;
static void gateEvent(const char* key, unsigned long long value) {
    std::cerr << "{\"native\":\"" << key << "\",\"value\":" << value << "}\n";
}
static void controlEvent(unsigned i, const char* key, unsigned long long value) {
    const auto label = std::string("a1_control_h") + std::to_string(i) + "_" + key;
    gateEvent(label.c_str(), value);
}
static HANDLE keep(HANDLE h) {
    pg::require(h && h != INVALID_HANDLE_VALUE, "fixture_handle");
    hostile.push_back(std::make_unique<pg::Handle>(h)); return h;
}
static BOOL WINAPI watchedAttribute(LPPROC_THREAD_ATTRIBUTE_LIST list, DWORD flags, DWORD_PTR key,
    PVOID value, SIZE_T bytes, PVOID previous, PSIZE_T returned) {
    // Only this separate fixture defers installing HANDLE_LIST until its one
    // synthetic capability exists. The normal gate-host.cpp is unchanged.
    if (key == PROC_THREAD_ATTRIBUTE_HANDLE_LIST) {
        if (fixtureAttributes || flags || previous || returned || bytes != sizeof(permittedHandles)) {
            SetLastError(ERROR_INVALID_DATA); return FALSE;
        }
        fixtureAttributes = list;
    } else if (!UpdateProcThreadAttribute(list, flags, key, value, bytes, previous, returned)) return FALSE;
    const DWORD_PTR keys[]{PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY, PROC_THREAD_ATTRIBUTE_JOB_LIST,
        PROC_THREAD_ATTRIBUTE_HANDLE_LIST, PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY};
    for (unsigned i = 0; i < 5; ++i) if (key == keys[i]) { attributeMask |= 1u << i; ++attributeCount; }
    if (key == PROC_THREAD_ATTRIBUTE_HANDLE_LIST) {
        if (bytes != sizeof(permittedHandles)) { SetLastError(ERROR_INVALID_DATA); return FALSE; }
        memcpy(permittedHandles, value, bytes);
    }
    return TRUE;
}
static BOOL WINAPI checkedCreate(HANDLE token, LPCWSTR application, LPWSTR command,
    LPSECURITY_ATTRIBUTES processSA, LPSECURITY_ATTRIBUTES threadSA, BOOL inherit,
    DWORD flags, LPVOID environment, LPCWSTR cwd, LPSTARTUPINFOW startup,
    LPPROCESS_INFORMATION process) {
    try {
        pg::require(inherit && (flags & CREATE_SUSPENDED) && (flags & EXTENDED_STARTUPINFO_PRESENT), "creation_flags");
        pg::require(attributeMask == 31 && attributeCount == 5, "original_five_attributes");
        pg::require(permittedHandles[0] == startup->hStdInput && permittedHandles[1] == startup->hStdOutput &&
            permittedHandles[2] == startup->hStdError, "original_three_handles");
        a3::emit("attribute_mask", attributeMask); a3::emit("attribute_count", attributeCount);
        a3::emit("inheritance_count", 4);
        a4::emit("case", a4::caseNumber);
        a4::emit("normal_inheritance_count", 3);
        const std::filesystem::path path(application), root = path.parent_path();
        pg::require(path.filename() == L"probe.exe", "a4_fixed_probe_only");
        imagePin = std::make_unique<pg::ImagePin>(path.wstring(), PROBE_SHA256, PROBE_BYTES);
        gateEvent("prelaunch_image_verified", 1);
        SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
            auto read = keep(CreateFileW((root / "smuggled-read.txt").c_str(), GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr));
            auto write = keep(CreateFileW((root / "smuggled-write.txt").c_str(), GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr));
            auto mapping = keep(CreateFileMappingW(write, &sa, PAGE_READWRITE, 0, 0, nullptr));
            auto event = keep(CreateEventW(&sa, TRUE, FALSE, nullptr));
            auto parent = keep(OpenProcess(PROCESS_DUP_HANDLE | PROCESS_QUERY_LIMITED_INFORMATION, TRUE, GetCurrentProcessId()));
            HANDLE values[]{read, write, mapping, event, parent}; memcpy(diagnosticHandles, values, sizeof(values));
            hd::Expected expected{}; expected.read = pg::identity(read); expected.write = pg::identity(write);
            expected.readHandle = read; expected.hostPid = GetCurrentProcessId();
            FILETIME creation{}, exit{}, kernel{}, user{};
            pg::require(GetProcessTimes(GetCurrentProcess(), &creation, &exit, &kernel, &user), "host_creation");
            expected.hostCreation = hd::filetime(creation);
            for (unsigned i = 0; i < 5; ++i) {
                auto result = hd::inspect(i, values[i], expected, values[i], controlEvent);
                pg::require(result.outcome == hd::Access && result.attempted && result.ok, "shared_probe_positive_control");
            }
            LARGE_INTEGER zero{}; char changed[32]{}; DWORD count = 0;
            pg::require(SetFilePointerEx(write, zero, nullptr, FILE_BEGIN) &&
                ReadFile(write, changed, 32, &count, nullptr) && count == 32 && changed[0] == '!' && changed[1] == 'M', "control_modifications_observed");
            pg::require(WaitForSingleObject(event, 0) == WAIT_OBJECT_0 && ResetEvent(event), "event_control_observed");
            memset(changed, 'S', sizeof(changed));
            pg::require(SetFilePointerEx(write, zero, nullptr, FILE_BEGIN) &&
                WriteFile(write, changed, 32, &count, nullptr) && count == 32 && FlushFileBuffers(write), "restore_only_control_fixture");
            gateEvent("a1_control_effects_verified_and_restored", 1);

        a3::state = std::make_shared<a3::State>();
        for (unsigned i = 0; i < 5; ++i) {
            DWORD handleFlags = 0;
            pg::require(GetHandleInformation(diagnosticHandles[i], &handleFlags) && (handleFlags & HANDLE_FLAG_INHERIT), "hostile_inheritable");
            a3::state->references[i] = a3::retain(diagnosticHandles[i]);
        }
        for (unsigned i = 0; i < 3; ++i) {
            a3::state->references[i + 5] = a3::retain(permittedHandles[i]);
            a3::state->pipeValues[i] = (uintptr_t)permittedHandles[i];
        }
        gateEvent("hostile_handles_inheritable", 5); gateEvent("hostile_positive_controls", 1);
        a4::originalValue = (uintptr_t)read;
        a4::originalId = pg::identity(read);
        HANDLE inherited = read;
        if (a4::caseNumber == 2) {
            HANDLE alias = nullptr;
            pg::require(DuplicateHandle(GetCurrentProcess(), read, GetCurrentProcess(), &alias,
                0, TRUE, DUPLICATE_SAME_ACCESS), "a4_local_alias");
            inherited = keep(alias);
            pg::require(alias != read && CompareObjectHandles(alias, read), "a4_alias_object");
        }
        DWORD originalFlags = 0, inheritedFlags = 0;
        pg::require(GetHandleInformation(read, &originalFlags) && originalFlags == HANDLE_FLAG_INHERIT &&
            GetHandleInformation(inherited, &inheritedFlags) && inheritedFlags == HANDLE_FLAG_INHERIT,
            "a4_inheritance_eligibility");
        pg::require(CompareObjectHandles(inherited, read) && pg::equal(pg::identity(inherited), a4::originalId),
            "a4_inherited_identity");
        a4::inheritedValue = (uintptr_t)inherited;
        memcpy(fixtureHandles, permittedHandles, sizeof(permittedHandles)); fixtureHandles[3] = inherited;
        for (unsigned i = 0; i < 3; ++i) pg::require(fixtureHandles[i] != inherited, "a4_distinct_pipe");
        if (a4::caseNumber == 2) for (HANDLE h : fixtureHandles) pg::require(h != read, "a4_original_excluded");
        auto extended = reinterpret_cast<STARTUPINFOEXW*>(startup);
        pg::require(fixtureAttributes && fixtureAttributes == extended->lpAttributeList, "a4_attribute_binding");
        pg::require(UpdateProcThreadAttribute(fixtureAttributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            fixtureHandles, sizeof(fixtureHandles), nullptr, nullptr), "a4_fixture_handle_list");
        a4::emit("original_handle", (uintptr_t)read); a4::emit("inherited_handle", (uintptr_t)inherited);
        a4::emit("original_flags", originalFlags); a4::emit("inherited_flags", inheritedFlags);
        a4::emit("parent_same_object", 1); a4::emit("original_in_list", a4::caseNumber == 1);
        unsigned long long halves[2]{}; memcpy(halves, a4::originalId.FileId.Identifier, sizeof(halves));
        a4::emit("original_volume", a4::originalId.VolumeSerialNumber);
        a4::emit("original_file_low", halves[0]); a4::emit("original_file_high", halves[1]);
        a4::emit("fixture_list_installed", 1);
        for (unsigned i = 0; i < 4; ++i) a4::emit(("inherit_" + std::to_string(i)).c_str(), (uintptr_t)fixtureHandles[i]);
        imagePin->recheck();
        // The other four attributes, environment, token and Job pass through unchanged.
        BOOL ok = CreateProcessAsUserW(token, application, command, processSA,
            threadSA, inherit, flags, environment, cwd, startup, process);
        if (!ok) return FALSE;
        a3::state->pid = process->dwProcessId; a3::state->tid = process->dwThreadId;
        a3::state->originalProcess = process->hProcess; a3::state->originalThread = process->hThread;
        a3::emit("created_pid", process->dwProcessId); a3::emit("created_tid", process->dwThreadId);
        try {
            a3::state->process = a3::retain(process->hProcess);
            a3::state->thread = a3::retain(process->hThread);
            FILETIME created{}, exited{}, childKernel{}, childUser{};
            pg::require(GetProcessTimes(process->hProcess, &created, &exited, &childKernel, &childUser), "a3_created_identity");
            a3::state->creation = a3::timeValue(created);
            imagePin->verifySuspended(process->hProcess);
            gateEvent("launched_image_independently_verified", 1);
        } catch (...) {
            BOOL killed = TerminateProcess(process->hProcess, 127);
            DWORD waited = WaitForSingleObject(process->hProcess, 3000);
            a3::emit("creation_abort_terminated", killed && waited == WAIT_OBJECT_0);
            CloseHandle(process->hThread); CloseHandle(process->hProcess); *process = {};
            throw;
        }
        return TRUE;
    } catch (const pg::Failure& e) {
        std::cerr << "{\"native\":\"gate_refusal_" << e.stage << "\",\"value\":" << e.error << "}\n";
        SetLastError(ERROR_INVALID_DATA); return FALSE;
    }
}
#define CreateProcessAsUserW checkedCreate
#define UpdateProcThreadAttribute watchedAttribute
#define wmain accepted_harness_main
// Generated from the hash-pinned accepted harness using exactly two insertions:
// inspection before the unreachable resume; a typed expected-refusal cleanup path.
#include "a4-fixture-harness.h"
#undef wmain
#undef CreateProcessAsUserW
#undef UpdateProcThreadAttribute
int wmain(int argc, wchar_t** argv) {
    if (argc != 3 || std::wstring(argv[2]) != L"probe") return 64;
    if (std::wstring(argv[1]) == L"A4-01") a4::caseNumber = 1;
    else if (std::wstring(argv[1]) == L"A4-02") a4::caseNumber = 2;
    else return 64;
    wchar_t mode[] = L"sealed"; wchar_t* arguments[]{argv[0], mode, argv[2]};
    int code = accepted_harness_main(3, arguments);
    if (diagnosticHandles[3]) {
        DWORD eventState = WaitForSingleObject(diagnosticHandles[3], 0);
        a3::emit("hostile_event_after_child", eventState);
        if (eventState != WAIT_TIMEOUT) code = 1;
    }
    imagePin.reset(); hostile.clear(); a3::state.reset();
    return code;
}
