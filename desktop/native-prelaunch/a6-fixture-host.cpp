// A6 diagnostic-only fixture launcher. Never used by the normal candidate or desktop.
#include "identity.h"
#include "handle-diagnostic.h"
#include "a6-fixture-inspection.h"
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
        a3::emit("inheritance_count", a6::handleCount);
        a6::emit("case", a6::caseNumber); a6::emit("sequence", a6::caseNumber - 11);
        a6::emit("kind", a6::kind); a6::emit("normal_inheritance_count", 3);
        const std::filesystem::path path(application), root = path.parent_path();
        pg::require(path.filename() == L"probe.exe", "a6_fixed_probe_only");
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
        a6::readId = expected.read;
        HANDLE intended = nullptr;
        if (a6::caseNumber == 12) {
            intended = keep(CreateSemaphoreExW(&sa, 0, 1, nullptr, 0,
                SYNCHRONIZE | SEMAPHORE_MODIFY_STATE));
            LONG previous = -1;
            pg::require(WaitForSingleObject(intended, 0) == WAIT_TIMEOUT &&
                ReleaseSemaphore(intended, 1, &previous) && previous == 0 &&
                WaitForSingleObject(intended, 0) == WAIT_OBJECT_0 &&
                WaitForSingleObject(intended, 0) == WAIT_TIMEOUT, "a6_semaphore_positive_control");
            a6::emit("semaphore_initial_count", 0); a6::emit("semaphore_maximum_count", 1);
            a6::emit("semaphore_access", SYNCHRONIZE | SEMAPHORE_MODIFY_STATE);
            a6::emit("semaphore_control_restored", 1);
        } else if (a6::caseNumber == 13) {
            intended = keep(CreateFileW((root / "smuggled-read.txt").c_str(), GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr));
            auto separateId = pg::identity(intended);
            SetLastError(ERROR_SUCCESS);
            BOOL same = CompareObjectHandles(intended, read);
            DWORD comparison = same ? 0 : GetLastError();
            pg::require(!same && comparison == ERROR_NOT_SAME_OBJECT &&
                pg::equal(separateId, expected.read), "a6_separate_open_identity");
            char data[32]{}; DWORD n = 0;
            pg::require(ReadFile(intended, data, sizeof(data), &n, nullptr) && n == 32,
                "a6_separate_read_control");
            for (char ch : data) pg::require(ch == 'R', "a6_separate_read_marker");
            a6::emit("separate_access", GENERIC_READ); a6::emit("separate_read_marker", 1);
            a6::emit("separate_file_same", 1); a6::emit("separate_object_same", same);
            a6::emit("separate_object_error", comparison);
        } else {
            HANDLE reader = nullptr, writer = nullptr;
            pg::require(CreatePipe(&reader, &writer, &sa, 4096), "a6_wrong_pipe_create");
            intended = keep(reader); keep(writer);
            pg::require(SetHandleInformation(writer, HANDLE_FLAG_INHERIT, 0), "a6_pipe_writer_private");
            SetLastError(ERROR_SUCCESS);
            BOOL same = CompareObjectHandles(reader, permittedHandles[0]);
            DWORD comparison = same ? 0 : GetLastError();
            pg::require(!same && comparison == ERROR_NOT_SAME_OBJECT &&
                GetFileType(reader) == FILE_TYPE_PIPE, "a6_wrong_pipe_identity");
            DWORD available = 0;
            pg::require(PeekNamedPipe(reader, nullptr, 0, nullptr, &available, nullptr) && !available,
                "a6_wrong_pipe_empty");
            a6::emit("wrong_pipe_role", 0); a6::emit("wrong_pipe_object_same", same);
            a6::emit("wrong_pipe_object_error", comparison); a6::emit("wrong_pipe_empty", 1);
        }
        a6::intended = intended; a6::inheritedValue = (uintptr_t)intended;
        a6::intendedPin = std::make_shared<pg::Handle>(a3::retain(intended));
        a6::originalValue = a6::caseNumber == 13 ? (uintptr_t)read :
            a6::caseNumber == 14 ? (uintptr_t)permittedHandles[0] : 0;
        DWORD inheritedFlags = 0;
        pg::require(GetHandleInformation(intended, &inheritedFlags) && inheritedFlags == HANDLE_FLAG_INHERIT,
            "a6_inheritance_eligibility");
        memcpy(fixtureHandles, permittedHandles, sizeof(permittedHandles));
        if (a6::caseNumber == 14) { fixtureHandles[0] = intended; startup->hStdInput = intended; }
        else fixtureHandles[3] = intended;
        auto extended = reinterpret_cast<STARTUPINFOEXW*>(startup);
        pg::require(fixtureAttributes && fixtureAttributes == extended->lpAttributeList, "a6_attribute_binding");
        pg::require(UpdateProcThreadAttribute(fixtureAttributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            fixtureHandles, a6::handleCount * sizeof(HANDLE), nullptr, nullptr), "a6_fixture_handle_list");
        a6::emit("original_handle", a6::originalValue); a6::emit("inherited_handle", a6::inheritedValue);
        a6::emit("inherited_flags", inheritedFlags); a6::emit("fixture_list_installed", 1);
        for (unsigned i = 0; i < a6::handleCount; ++i)
            a6::emit(("inherit_" + std::to_string(i)).c_str(), (uintptr_t)fixtureHandles[i]);
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
#include "a6-fixture-harness.h"
#undef wmain
#undef CreateProcessAsUserW
#undef UpdateProcThreadAttribute
int wmain(int argc, wchar_t** argv) {
    if (argc != 3 || std::wstring(argv[2]) != L"probe") return 64;
    if (!a6::select(argv[1])) return 64;
    wchar_t mode[] = L"sealed"; wchar_t* arguments[]{argv[0], mode, argv[2]};
    int code = accepted_harness_main(3, arguments);
    if (diagnosticHandles[3]) {
        DWORD eventState = WaitForSingleObject(diagnosticHandles[3], 0);
        a3::emit("hostile_event_after_child", eventState);
        if (eventState != WAIT_TIMEOUT) code = 1;
    }
    if (a6::caseNumber == 12 && a6::intended) {
        DWORD state = WaitForSingleObject(a6::intended, 0);
        a6::emit("semaphore_after_child", state);
        if (state != WAIT_TIMEOUT) code = 1;
    }
    imagePin.reset(); hostile.clear(); a3::state.reset(); a6::intendedPin.reset();
    return code;
}
