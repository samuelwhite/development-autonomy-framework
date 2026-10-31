// A3 case 01 only. Accepted source/configuration remain byte-identical.
#include "identity.h"
#include "handle-diagnostic.h"
#include "suspended-inspection.h"
#include <iostream>
#include <fstream>
#include "probe-identity.h"
namespace pg = prelaunch;
static std::unique_ptr<pg::ImagePin> imagePin;
static std::vector<std::unique_ptr<pg::Handle>> hostile;
static HANDLE diagnosticHandles[5]{}, permittedHandles[3]{};
static DWORD attributeMask = 0, attributeCount = 0;
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
    BOOL ok = UpdateProcThreadAttribute(list, flags, key, value, bytes, previous, returned);
    if (!ok) return FALSE;
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
        a3::emit("inheritance_count", 3);
        const std::filesystem::path path(application), root = path.parent_path();
        pg::require(path.filename() == L"probe.exe", "a3_fixed_probe_only");
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
        imagePin->recheck();
        // Pass through the original environment and all five original attributes.
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
// inspection before ResumeThread; a typed successful-feasibility cleanup path.
#include "a3-harness.h"
#undef wmain
#undef CreateProcessAsUserW
#undef UpdateProcThreadAttribute
int wmain(int argc, wchar_t** argv) {
    if (argc != 3 || std::wstring(argv[1]) != L"case-01" || std::wstring(argv[2]) != L"probe") return 64;
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
