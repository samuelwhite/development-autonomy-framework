// Standalone M2.1 feasibility experiment. NOT shipped or an execution controller.
// Only launches the adjacent bundled Python with the fixed adjacent probe.
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <userenv.h>
#include <aclapi.h>
#include <sddl.h>
#include <wincred.h>
#include <tlhelp32.h>
#include <wincrypt.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#pragma comment(lib, "userenv.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "crypt32.lib")
#pragma comment(lib, "onecoreuap.lib")
namespace fs = std::filesystem;
static void check(bool ok, const char* operation) {
    if (!ok) throw std::string(operation) + ": " + std::to_string(GetLastError());
}
static void event(const char* name, unsigned long long value) {
    std::cerr << "{\"native\":\"" << name << "\",\"value\":" << value << "}\n";
}
static std::string utf8(const std::wstring& s) {
    int n = WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0, nullptr, nullptr);
    std::string r(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), r.data(), n, nullptr, nullptr);
    return r;
}
static void grant(const fs::path& p, PSID sid, DWORD access, bool inherit) {
    PACL old = nullptr, updated = nullptr;
    PSECURITY_DESCRIPTOR sd = nullptr;
    check(GetNamedSecurityInfoW(p.c_str(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        nullptr, nullptr, &old, nullptr, &sd) == ERROR_SUCCESS, "read ACL");
    EXPLICIT_ACCESSW e{};
    e.grfAccessPermissions = access;
    e.grfAccessMode = GRANT_ACCESS;
    e.grfInheritance = inherit ? SUB_CONTAINERS_AND_OBJECTS_INHERIT : NO_INHERITANCE;
    e.Trustee.TrusteeForm = TRUSTEE_IS_SID;
    e.Trustee.ptstrName = (LPWSTR)sid;
    check(SetEntriesInAclW(1, &e, old, &updated) == ERROR_SUCCESS, "merge ACL");
    check(SetNamedSecurityInfoW((LPWSTR)p.c_str(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        nullptr, nullptr, updated, nullptr) == ERROR_SUCCESS, "write ACL");
    LocalFree(updated); LocalFree(sd);
}
struct Sealed {
    HANDLE handle;
    PSECURITY_DESCRIPTOR descriptor;
    PACL dacl;
};
// Retain WRITE_DAC handles before restricting owner rights. Restore only our
// freshly created profile in reverse order; never modify an existing profile.
static std::vector<Sealed> sealed;
static HKEY sealedRegistry = nullptr;
static PSECURITY_DESCRIPTOR registryDescriptor = nullptr;
static PACL registryDacl = nullptr;
static PSID appSid = nullptr;
static PACL readonlyAcl(DWORD appAccess, bool directory) {
    HANDLE token = nullptr;
    check(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token), "ACL host token");
    BYTE userBuffer[1024]; DWORD bytes = 0;
    check(GetTokenInformation(token, TokenUser, userBuffer, sizeof(userBuffer), &bytes), "ACL host SID");
    PSID system = nullptr, ownerRights = nullptr;
    check(ConvertStringSidToSidW(L"S-1-5-18", &system), "system SID");
    check(ConvertStringSidToSidW(L"S-1-3-4", &ownerRights), "owner rights SID");
    EXPLICIT_ACCESSW e[4]{};
    PSID identities[]{((PTOKEN_USER)userBuffer)->User.Sid, system, appSid, ownerRights};
    for (int i = 0; i != 4; ++i) {
        e[i].grfAccessMode = SET_ACCESS;
        e[i].grfInheritance = directory ? SUB_CONTAINERS_AND_OBJECTS_INHERIT : NO_INHERITANCE;
        e[i].Trustee.TrusteeForm = TRUSTEE_IS_SID;
        e[i].Trustee.ptstrName = (LPWSTR)identities[i];
    }
    e[0].grfAccessPermissions = GENERIC_ALL;
    e[1].grfAccessPermissions = GENERIC_ALL;
    e[2].grfAccessPermissions = appAccess;
    // Presence of OWNER RIGHTS removes implicit owner WRITE_DAC. Host keeps
    // its explicit full-access user ACE; the restricted principal gets read only.
    e[3].grfAccessPermissions = READ_CONTROL;
    PACL updated = nullptr;
    check(SetEntriesInAclW(4, e, nullptr, &updated) == ERROR_SUCCESS, "build read-only ACL");
    CloseHandle(token); LocalFree(system); LocalFree(ownerRights);
    return updated;
}
static void sealRegistry(HANDLE token) {
    check(ImpersonateLoggedOnUser(token), "impersonate child for its registry location");
    HRESULT hr = GetAppContainerRegistryLocation(READ_CONTROL | WRITE_DAC | KEY_READ, &sealedRegistry);
    check(RevertToSelf(), "revert registry-location impersonation");
    check(SUCCEEDED(hr), "open child profile registry ACL handle");
    check(GetSecurityInfo(sealedRegistry, SE_REGISTRY_KEY, DACL_SECURITY_INFORMATION,
        nullptr, nullptr, &registryDacl, nullptr, &registryDescriptor) == ERROR_SUCCESS, "read registry ACL");
    PACL updated = readonlyAcl(KEY_READ, true);
    check(SetSecurityInfo(sealedRegistry, SE_REGISTRY_KEY, DACL_SECURITY_INFORMATION |
        PROTECTED_DACL_SECURITY_INFORMATION, nullptr, nullptr, updated, nullptr) == ERROR_SUCCESS, "seal registry");
    LocalFree(updated);
}
static void seal(const fs::path& p, PSID) {
    HANDLE h = CreateFileW(p.c_str(), READ_CONTROL | WRITE_DAC,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    check(h != INVALID_HANDLE_VALUE, "open profile ACL handle");
    PACL old = nullptr, updated = nullptr;
    PSECURITY_DESCRIPTOR sd = nullptr;
    check(GetSecurityInfo(h, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr,
        &old, nullptr, &sd) == ERROR_SUCCESS, "read profile ACL");
    updated = readonlyAcl(FILE_GENERIC_READ | FILE_GENERIC_EXECUTE, fs::is_directory(p));
    sealed.push_back({h, sd, old});
    check(SetSecurityInfo(h, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION |
        PROTECTED_DACL_SECURITY_INFORMATION, nullptr, nullptr, updated, nullptr) == ERROR_SUCCESS,
        "seal profile ACL");
    LocalFree(updated);
}
static DWORD parentPid() {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    check(snapshot != INVALID_HANDLE_VALUE, "snapshot parent");
    PROCESSENTRY32W entry{}; entry.dwSize = sizeof(entry);
    DWORD pid = 0;
    if (Process32FirstW(snapshot, &entry)) do {
        if (entry.th32ProcessID == GetCurrentProcessId()) { pid = entry.th32ParentProcessID; break; }
    } while (Process32NextW(snapshot, &entry));
    CloseHandle(snapshot);
    check(pid != 0, "find parent");
    return pid;
}
int wmain(int argc, wchar_t** argv) {
    const std::wstring mode = argc == 2 ? argv[1] : L"";
    if (mode != L"baseline" && mode != L"sealed" && mode != L"hold" &&
        mode != L"cpu" && mode != L"memory" && mode != L"debug") return 64;
    HANDLE job = nullptr, process = nullptr, thread = nullptr, parent = nullptr;
    PSID sid = nullptr;
    std::wstring profileName;
    bool created = false, credentialCreated = false, registryFixtureCreated = false;
    int result = 1;
    try {
        HANDLE hostToken = nullptr; check(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &hostToken), "host token");
        DWORD hostValue = 0, hostBytes = 0;
        check(GetTokenInformation(hostToken, TokenIsAppContainer, &hostValue, sizeof(hostValue), &hostBytes), "host AC query");
        event("host_appcontainer", hostValue);
        TOKEN_ELEVATION elevation{};
        check(GetTokenInformation(hostToken, TokenElevation, &elevation, sizeof(elevation), &hostBytes), "host elevation");
        event("host_elevated", elevation.TokenIsElevated); CloseHandle(hostToken);
        wchar_t exe[MAX_PATH]; check(GetModuleFileNameW(nullptr, exe, MAX_PATH) != 0, "helper path");
        const fs::path root = fs::path(exe).parent_path();
        GUID guid{}; check(SUCCEEDED(CoCreateGuid(&guid)), "GUID");
        wchar_t guidText[40]; StringFromGUID2(guid, guidText, 40);
        profileName = L"DAF.M21.Feasibility." + std::wstring(guidText + 1, 36);
        HRESULT hr = CreateAppContainerProfile(profileName.c_str(), L"DAF isolation test",
            L"Temporary standalone feasibility profile", nullptr, 0, &sid);
        check(SUCCEEDED(hr), "create fresh AppContainer profile"); created = true; appSid = sid;
        LPWSTR sidText = nullptr, profileText = nullptr;
        check(ConvertSidToStringSidW(sid, &sidText), "SID string");
        check(SUCCEEDED(GetAppContainerFolderPath(sidText, &profileText)), "profile folder");
        const fs::path profile(profileText);
        // A marker lets the maintainer runner clean this exact owned profile if
        // the helper is deliberately killed during job-containment testing.
        std::ofstream(root / "owned-profile.txt") << utf8(profileName) << "\n" << utf8(profile.wstring()) << "\n";
        LocalFree(sidText); CoTaskMemFree(profileText);
        fs::create_directories(profile / "Temp");
        std::ofstream(profile / "owned-sentinel.txt") << "synthetic profile sentinel";
        // Only packaged code/runtime and the explicit fixture receive access.
        grant(root, sid, FILE_TRAVERSE | FILE_READ_ATTRIBUTES | SYNCHRONIZE, false);
        grant(root / "runtime", sid, FILE_GENERIC_READ | FILE_GENERIC_EXECUTE, true);
        grant(root / "probe.py", sid, FILE_GENERIC_READ, false);
        grant(root / "allowed.txt", sid, FILE_GENERIC_READ, false);
        grant(root / "protected.bin", sid, FILE_GENERIC_READ, false);
        // Adversarial environmental fixture: another application can expose a
        // low-integrity file to ALL_RESTRICTED_APPLICATION_PACKAGES. This is NOT
        // in this attempt's explicit read/write allowlist and has no task SID ACE.
        PSID allRestricted = nullptr;
        check(ConvertStringSidToSidW(L"S-1-15-2-2", &allRestricted), "all restricted apps SID");
        grant(root / "ambient-shared.txt", allRestricted, FILE_GENERIC_READ | FILE_GENERIC_WRITE, false);
        LocalFree(allRestricted);
        HANDLE fixtureToken = nullptr; BYTE fixtureUser[1024]; DWORD fixtureBytes = 0;
        check(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &fixtureToken), "fixture owner token");
        check(GetTokenInformation(fixtureToken, TokenUser, fixtureUser, sizeof(fixtureUser), &fixtureBytes), "fixture owner SID");
        grant(root / "ambient-shared.txt", ((PTOKEN_USER)fixtureUser)->User.Sid, FILE_ALL_ACCESS, false);
        CloseHandle(fixtureToken);
        PSECURITY_DESCRIPTOR lowDescriptor = nullptr; PACL lowSacl = nullptr;
        BOOL saclPresent = FALSE, saclDefaulted = FALSE;
        check(ConvertStringSecurityDescriptorToSecurityDescriptorW(L"S:(ML;;NW;;;LW)",
            SDDL_REVISION_1, &lowDescriptor, nullptr), "low-integrity fixture label");
        check(GetSecurityDescriptorSacl(lowDescriptor, &saclPresent, &lowSacl, &saclDefaulted), "read low label");
        DWORD labelResult = SetNamedSecurityInfoW((LPWSTR)(root / "ambient-shared.txt").c_str(), SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION, nullptr, nullptr, nullptr, lowSacl);
        event("fixture_label_result", labelResult);
        check(labelResult == ERROR_SUCCESS, "set fixture low label");
        LocalFree(lowDescriptor);
        const BYTE secret[] = "DAF synthetic credential; no real secret";
        CREDENTIALW credential{};
        credential.Type = CRED_TYPE_GENERIC; credential.TargetName = (LPWSTR)profileName.c_str();
        credential.CredentialBlobSize = sizeof(secret); credential.CredentialBlob = (LPBYTE)secret;
        credential.Persist = CRED_PERSIST_SESSION; credential.UserName = (LPWSTR)L"DAF probe";
        check(CredWriteW(&credential, 0), "write synthetic host credential"); credentialCreated = true;
        HKEY fixtureKey = nullptr; DWORD disposition = 0;
        const std::wstring fixtureName = L"Software\\" + profileName;
        check(RegCreateKeyExW(HKEY_CURRENT_USER, fixtureName.c_str(), 0, nullptr, 0,
            KEY_WRITE, nullptr, &fixtureKey, &disposition) == ERROR_SUCCESS, "create synthetic host registry key");
        check(disposition == REG_CREATED_NEW_KEY, "fresh synthetic registry key required");
        registryFixtureCreated = true;
        check(RegSetValueExW(fixtureKey, L"HostPrivateSentinel", 0, REG_BINARY, secret,
            sizeof(secret)) == ERROR_SUCCESS, "write synthetic registry value"); RegCloseKey(fixtureKey);
        DATA_BLOB plain{sizeof(secret), (BYTE*)secret}, protectedBlob{};
        check(CryptProtectData(&plain, nullptr, nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN,
            &protectedBlob), "protect synthetic data");
        std::ofstream blob(root / "protected.bin", std::ios::binary | std::ios::trunc);
        blob.write((char*)protectedBlob.pbData, protectedBlob.cbData); blob.close();
        LocalFree(protectedBlob.pbData);
        parent = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, parentPid());
        check(parent != nullptr, "open supervising parent");
        job = CreateJobObjectW(nullptr, nullptr); check(job != nullptr, "create job");
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_PROCESS_MEMORY |
            JOB_OBJECT_LIMIT_PROCESS_TIME;
        limits.BasicLimitInformation.ActiveProcessLimit = 1;
        limits.BasicLimitInformation.PerProcessUserTimeLimit.QuadPart = 20000000;
        limits.ProcessMemoryLimit = 128 * 1024 * 1024;
        check(SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits)), "set job limits");
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION actualLimits{};
        check(QueryInformationJobObject(job, JobObjectExtendedLimitInformation, &actualLimits,
            sizeof(actualLimits), nullptr), "read actual job limits");
        event("job_limit_flags", actualLimits.BasicLimitInformation.LimitFlags);
        event("job_process_limit", actualLimits.BasicLimitInformation.ActiveProcessLimit);
        event("job_memory_bytes", actualLimits.ProcessMemoryLimit);
        event("job_cpu_100ns", actualLimits.BasicLimitInformation.PerProcessUserTimeLimit.QuadPart);
        SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
        HANDLE inputRead = nullptr, inputWrite = nullptr;
        check(CreatePipe(&inputRead, &inputWrite, &sa, 0), "stdin pipe");
        CloseHandle(inputWrite);
        HANDLE output = GetStdHandle(STD_OUTPUT_HANDLE), error = GetStdHandle(STD_ERROR_HANDLE);
        check(SetHandleInformation(output, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT), "stdout inherit");
        check(SetHandleInformation(error, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT), "stderr inherit");
        HANDLE handles[]{inputRead, output, error};
        STARTUPINFOEXW start{}; start.StartupInfo.cb = sizeof(start);
        start.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        start.StartupInfo.hStdInput = inputRead; start.StartupInfo.hStdOutput = output; start.StartupInfo.hStdError = error;
        SIZE_T size = 0; InitializeProcThreadAttributeList(nullptr, 5, 0, &size);
        std::vector<BYTE> storage(size); start.lpAttributeList = (LPPROC_THREAD_ATTRIBUTE_LIST)storage.data();
        check(InitializeProcThreadAttributeList(start.lpAttributeList, 5, 0, &size), "attributes");
        SECURITY_CAPABILITIES capabilities{}; capabilities.AppContainerSid = sid;
        PSID *groups = nullptr, *capabilitySids = nullptr; DWORD groupCount = 0, capabilityCount = 0;
        check(DeriveCapabilitySidsFromName(L"registryRead", &groups, &groupCount,
            &capabilitySids, &capabilityCount), "derive registryRead");
        check(capabilityCount == 1, "single registryRead SID");
        SID_AND_ATTRIBUTES readCapability{capabilitySids[0], SE_GROUP_ENABLED};
        capabilities.Capabilities = &readCapability; capabilities.CapabilityCount = 1;
        DWORD optOut = PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT;
        DWORD children = PROCESS_CREATION_CHILD_PROCESS_RESTRICTED;
        auto attribute = [&](DWORD_PTR key, void* value, SIZE_T bytes) {
            check(UpdateProcThreadAttribute(start.lpAttributeList, 0, key, value, bytes, nullptr, nullptr), "set process attribute");
        };
        attribute(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, &capabilities, sizeof(capabilities));
        attribute(PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY, &optOut, sizeof(optOut));
        attribute(PROC_THREAD_ATTRIBUTE_JOB_LIST, &job, sizeof(job));
        attribute(PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles, sizeof(handles));
        attribute(PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY, &children, sizeof(children));
        wchar_t windows[MAX_PATH]; GetWindowsDirectoryW(windows, MAX_PATH);
        wchar_t localAppData[32768], userProfile[32768];
        check(GetEnvironmentVariableW(L"LOCALAPPDATA", localAppData, 32768) != 0, "host LOCALAPPDATA");
        check(GetEnvironmentVariableW(L"USERPROFILE", userProfile, 32768) != 0, "host USERPROFILE");
        std::vector<std::wstring> environment = {
            L"DAF_CREDENTIAL_TARGET=" + profileName, L"DAF_PROFILE=" + profile.wstring(),
            L"DAF_PROBE_MODE=" + mode, L"DAF_ROOT=" + root.wstring(),
            L"LOCALAPPDATA=" + std::wstring(localAppData),
            L"SystemRoot=" + std::wstring(windows), L"TEMP=" + (profile / L"Temp").wstring(),
            L"TMP=" + (profile / L"Temp").wstring(), L"USERPROFILE=" + std::wstring(userProfile)};
        std::wstring env;
        for (const auto& e : environment) { env += e; env += L'\0'; } env += L'\0';
        std::wstring command = L"\"" + (root / L"runtime" / L"python.exe").wstring() +
            L"\" -I -S -B -u \"" + (root / L"probe.py").wstring() + L"\"";
        PROCESS_INFORMATION pi{};
        check(CreateProcessW((root / L"runtime" / L"python.exe").c_str(), command.data(), nullptr,
            nullptr, TRUE, EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT |
            DETACHED_PROCESS | CREATE_SUSPENDED | (mode == L"debug" ? DEBUG_ONLY_THIS_PROCESS : 0),
            env.data(), (root / L"runtime").c_str(), &start.StartupInfo, &pi), "create LPAC Python");
        process = pi.hProcess; thread = pi.hThread;
        for (DWORD i = 0; i < groupCount; ++i) LocalFree(groups[i]); LocalFree(groups);
        for (DWORD i = 0; i < capabilityCount; ++i) LocalFree(capabilitySids[i]); LocalFree(capabilitySids);
        DeleteProcThreadAttributeList(start.lpAttributeList); CloseHandle(inputRead);
        HANDLE token = nullptr; check(OpenProcessToken(process, TOKEN_QUERY | TOKEN_DUPLICATE, &token), "child token");
        DWORD value = 0, returned = 0;
        check(GetTokenInformation(token, TokenIsAppContainer, &value, sizeof(value), &returned), "AppContainer token");
        event("appcontainer", value); check(value == 1, "AppContainer required");
        // This documented information class returns ERROR_INVALID_PARAMETER on
        // this Windows build. Record it, and test the actual LPAC ACL semantics.
        if (GetTokenInformation(token, TokenIsLessPrivilegedAppContainer, &value, sizeof(value), &returned))
            event("lpac_token_query", value);
        else event("lpac_token_query_error", GetLastError());
        HANDLE impersonation = nullptr;
        check(DuplicateToken(token, SecurityImpersonation, &impersonation), "duplicate token for AccessCheck");
        PSECURITY_DESCRIPTOR testDescriptor = nullptr;
        check(ConvertStringSecurityDescriptorToSecurityDescriptorW(
            L"O:WDG:WDD:(A;;0x3;;;WD)(A;;0x1;;;S-1-15-2-1)(A;;0x2;;;S-1-15-2-2)",
            SDDL_REVISION_1, &testDescriptor, nullptr), "LPAC test descriptor");
        GENERIC_MAPPING mapping{1, 2, 0, 3}; DWORD granted = 0;
        BYTE privilegeBuffer[1024]{}; DWORD privilegeSize = sizeof(privilegeBuffer); BOOL access = FALSE;
        check(AccessCheck(testDescriptor, impersonation, MAXIMUM_ALLOWED, &mapping,
            (PPRIVILEGE_SET)privilegeBuffer, &privilegeSize, &granted, &access), "LPAC AccessCheck");
        event("lpac_accesscheck_mask", granted);
        check(access && granted == 2, "LPAC must exclude ALL_APPLICATION_PACKAGES");
        LocalFree(testDescriptor);
        if (mode != L"baseline") sealRegistry(impersonation);
        CloseHandle(impersonation);
        BYTE caps[1024]{};
        check(GetTokenInformation(token, TokenCapabilities, caps, sizeof(caps), &returned), "capabilities");
        event("capability_count", ((PTOKEN_GROUPS)caps)->GroupCount);
        check(((PTOKEN_GROUPS)caps)->GroupCount == 1, "registryRead only");
        CloseHandle(token);
        BOOL inJob = FALSE; check(IsProcessInJob(process, job, &inJob), "job membership");
        check(inJob, "job required before resume"); event("job_at_creation", inJob);
        event("child_pid", pi.dwProcessId); event("helper_pid", GetCurrentProcessId());
        // CreateProcess initializes and resets parts of the profile ACL. Seal
        // AFTER process creation, while the child remains suspended in its job.
        if (mode != L"baseline") {
            std::vector<fs::path> paths{profile.parent_path()};
            for (const auto& e : fs::recursive_directory_iterator(profile.parent_path())) {
                check(!fs::is_symlink(e.symlink_status()), "profile must not contain links");
                paths.push_back(e.path());
            }
            for (auto i = paths.rbegin(); i != paths.rend(); ++i) seal(*i, sid);
        }
        check(ResumeThread(thread) != (DWORD)-1, "resume");
        if (mode == L"debug") {
            DEBUG_EVENT debug{}; ULONGLONG deadline = GetTickCount64() + 10000;
            while (GetTickCount64() < deadline && WaitForDebugEvent(&debug, 1000)) {
                DWORD continuation = DBG_CONTINUE;
                if (debug.dwDebugEventCode == LOAD_DLL_DEBUG_EVENT && debug.u.LoadDll.hFile) {
                    wchar_t path[32768]{};
                    GetFinalPathNameByHandleW(debug.u.LoadDll.hFile, path, 32768, 0);
                    std::cerr << "DLL " << utf8(path) << "\n"; CloseHandle(debug.u.LoadDll.hFile);
                }
                if (debug.dwDebugEventCode == CREATE_PROCESS_DEBUG_EVENT && debug.u.CreateProcessInfo.hFile)
                    CloseHandle(debug.u.CreateProcessInfo.hFile);
                if (debug.dwDebugEventCode == EXCEPTION_DEBUG_EVENT) {
                    event("debug_exception", debug.u.Exception.ExceptionRecord.ExceptionCode);
                    if (debug.u.Exception.ExceptionRecord.ExceptionCode != EXCEPTION_BREAKPOINT)
                        continuation = DBG_EXCEPTION_NOT_HANDLED;
                }
                ContinueDebugEvent(debug.dwProcessId, debug.dwThreadId, continuation);
                if (debug.dwDebugEventCode == EXIT_PROCESS_DEBUG_EVENT) break;
            }
        }
        HANDLE waiting[]{process, parent};
        const DWORD wait = WaitForMultipleObjects(2, waiting, FALSE, 10000);
        if (wait != WAIT_OBJECT_0) {
            event(wait == WAIT_OBJECT_0 + 1 ? "parent_death" : "wall_timeout", 1);
            check(TerminateJobObject(job, 125), "terminate job");
            check(WaitForSingleObject(process, 3000) == WAIT_OBJECT_0, "confirm termination");
        }
        DWORD code = 0; check(GetExitCodeProcess(process, &code), "exit code"); event("child_exit", code);
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
        check(QueryInformationJobObject(job, JobObjectBasicAccountingInformation, &accounting, sizeof(accounting), nullptr), "job accounting");
        event("active_after_wait", accounting.ActiveProcesses);
        result = code == 0 ? 0 : 1;
    } catch (const std::string& e) { std::cerr << "ERROR " << e << "\n"; }
      catch (const std::exception& e) { std::cerr << "ERROR " << e.what() << "\n"; }
    if (job) { TerminateJobObject(job, 126); CloseHandle(job); }
    if (process) { WaitForSingleObject(process, 3000); CloseHandle(process); }
    if (thread) CloseHandle(thread);
    if (parent) CloseHandle(parent);
    if (sealedRegistry) {
        if (registryDescriptor) event("restore_registry_acl", SetSecurityInfo(sealedRegistry,
            SE_REGISTRY_KEY, DACL_SECURITY_INFORMATION | UNPROTECTED_DACL_SECURITY_INFORMATION,
            nullptr, nullptr, registryDacl, nullptr));
        RegCloseKey(sealedRegistry); LocalFree(registryDescriptor);
    }
    for (auto i = sealed.rbegin(); i != sealed.rend(); ++i) {
        DWORD r = SetSecurityInfo(i->handle, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION |
            UNPROTECTED_DACL_SECURITY_INFORMATION, nullptr, nullptr, i->dacl, nullptr);
        event("restore_profile_acl", r); CloseHandle(i->handle); LocalFree(i->descriptor);
    }
    if (credentialCreated) event("delete_synthetic_credential", CredDeleteW(profileName.c_str(), CRED_TYPE_GENERIC, 0));
    if (registryFixtureCreated) event("delete_synthetic_registry_key", RegDeleteKeyW(HKEY_CURRENT_USER,
        (L"Software\\" + profileName).c_str()));
    if (created) {
        HRESULT cleanup = DeleteAppContainerProfile(profileName.c_str());
        event("delete_owned_profile_hresult", (unsigned long)cleanup);
        if (FAILED(cleanup)) result = 1;
    }
    if (sid) FreeSid(sid);
    return result;
}
