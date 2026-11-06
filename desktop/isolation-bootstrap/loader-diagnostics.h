// Diagnostic-only: derive the PEB field offset from the matching Microsoft PDB.
// Never alter IFEO, Windows ACLs, child token, imports or API return values.
#include <dbghelp.h>
#include <winternl.h>
#pragma comment(lib, "dbghelp.lib")
static BOOL CALLBACK symbolMessage(HANDLE, ULONG action, ULONG64 data, ULONG64) {
    if (action == CBA_DEBUG_INFO) std::cerr << "SYMBOL " << (const char*)data;
    return FALSE;
}
static void loaderSnaps(HANDLE child, const fs::path& root) {
    HANDLE self = GetCurrentProcess();
    auto cache = root / "symbols"; fs::create_directory(cache);
    auto search = L"srv*" + cache.wstring() + L"*https://msdl.microsoft.com/download/symbols";
    SymSetOptions(SYMOPT_UNDNAME | SYMOPT_DEFERRED_LOADS | SYMOPT_FAIL_CRITICAL_ERRORS |
        SYMOPT_EXACT_SYMBOLS | SYMOPT_NO_PROMPTS | SYMOPT_DEBUG);
    check(SymInitializeW(self, search.c_str(), FALSE), "initialize diagnostic symbol session");
    check(SymRegisterCallback64(self, symbolMessage, 0), "symbol diagnostics callback");
    wchar_t system[MAX_PATH]{}; check(GetSystemDirectoryW(system, MAX_PATH) != 0, "system directory");
    auto ntdll = fs::path(system) / "ntdll.dll";
    DWORD64 base = SymLoadModuleExW(self, nullptr, ntdll.c_str(), nullptr, 0, 0, nullptr, 0);
    check(base != 0, "load exact ntdll symbols");
    BYTE infoBuffer[sizeof(SYMBOL_INFO) + MAX_SYM_NAME]{};
    auto info = (PSYMBOL_INFO)infoBuffer;
    info->SizeOfStruct = sizeof(SYMBOL_INFO); info->MaxNameLen = MAX_SYM_NAME;
    check(SymGetTypeFromName(self, base, "_PEB", info), "Microsoft PDB _PEB type required");
    DWORD count = 0;
    check(SymGetTypeInfo(self, base, info->TypeIndex, TI_GET_CHILDRENCOUNT, &count), "PEB field count");
    check(count > 0 && count < 1000, "bounded PEB field count");
    std::vector<BYTE> buffer(sizeof(TI_FINDCHILDREN_PARAMS) + count * sizeof(ULONG));
    auto fields = (TI_FINDCHILDREN_PARAMS*)buffer.data(); fields->Count = count; fields->Start = 0;
    check(SymGetTypeInfo(self, base, info->TypeIndex, TI_FINDCHILDREN, fields), "PEB fields");
    DWORD offset = 0;
    for (DWORD i = 0; i < count; ++i) {
        wchar_t* name = nullptr;
        if (!SymGetTypeInfo(self, base, fields->ChildId[i], TI_GET_SYMNAME, &name)) continue;
        bool match = std::wstring(name) == L"NtGlobalFlag"; LocalFree(name);
        if (match) check(SymGetTypeInfo(self, base, fields->ChildId[i], TI_GET_OFFSET, &offset), "NtGlobalFlag offset");
    }
    check(offset != 0 && offset < 4096 && offset % 4 == 0, "validated symbol-derived flag offset");
    event("symbol_derived_NtGlobalFlag_offset", offset);
    IMAGEHLP_MODULEW64 module{}; module.SizeOfStruct = sizeof(module);
    check(SymGetModuleInfoW64(self, base, &module), "symbol module identity");
    wchar_t guid[40]; StringFromGUID2(module.PdbSig70, guid, 40);
    std::cerr << "PDB ntdll " << utf8(guid) << " age " << module.PdbAge << "\n";
    SymCleanup(self);
    using Query = NTSTATUS (NTAPI*)(HANDLE, PROCESSINFOCLASS, PVOID, ULONG, PULONG);
    auto query = (Query)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryInformationProcess");
    check(query != nullptr, "NtQueryInformationProcess export");
    PROCESS_BASIC_INFORMATION basic{};
    check(query(child, ProcessBasicInformation, &basic, sizeof(basic), nullptr) >= 0, "child PEB query");
    BYTE* address = (BYTE*)basic.PebBaseAddress + offset;
    ULONG flags = 0; SIZE_T transferred = 0;
    check(ReadProcessMemory(child, address, &flags, sizeof(flags), &transferred) && transferred == sizeof(flags), "read child diagnostic flags");
    event("child_NtGlobalFlag_before", flags);
    flags |= 2; // Microsoft FLG_SHOW_LDR_SNAPS; no other bit is changed.
    check(WriteProcessMemory(child, address, &flags, sizeof(flags), &transferred) && transferred == sizeof(flags), "enable only child loader snaps");
    event("child_NtGlobalFlag_after", flags);
}
