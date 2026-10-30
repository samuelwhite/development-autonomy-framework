// Fixed NT-call observation in the diagnostic child only. Software breakpoints
// restore the original instruction and single-step it; no result is substituted.
#include <map>
#include <algorithm>
struct AccessTrace {
    struct Call { DWORD tid, wanted; std::string api; std::wstring name; ULONG64 caller; DWORD share, options; };
    struct Breakpoint { BYTE original; std::string entry; std::vector<Call> calls; };
    struct Step { ULONG64 address; std::vector<HANDLE> paused; };
    struct Module { ULONG64 base, size; std::wstring name; };
    HANDLE child;
    std::map<ULONG64, Breakpoint> points;
    std::map<DWORD, Step> stepping;
    std::vector<DWORD> threads;
    std::vector<Module> modules;
    explicit AccessTrace(HANDLE p) : child(p) {}
    void read(ULONG64 at, void* buffer, SIZE_T bytes) {
        SIZE_T got = 0;
        check(ReadProcessMemory(child, (void*)at, buffer, bytes, &got) && got == bytes, "diagnostic read");
    }
    void byte(ULONG64 at, BYTE value) {
        SIZE_T wrote = 0;
        check(WriteProcessMemory(child, (void*)at, &value, 1, &wrote) && wrote == 1, "diagnostic breakpoint write");
        check(FlushInstructionCache(child, (void*)at, 1), "flush diagnostic breakpoint");
    }
    void breakpoint(ULONG64 at, const std::string& entry = "") {
        if (points.count(at)) return;
        BYTE original; read(at, &original, 1);
        check(original != 0xcc, "refuse pre-existing software breakpoint");
        points.emplace(at, Breakpoint{original, entry, {}}); byte(at, 0xcc);
    }
    std::wstring objectName(ULONG64 at) {
        if (!at) return L"<no object attributes>";
        OBJECT_ATTRIBUTES attributes{}; read(at, &attributes, sizeof(attributes));
        if (!attributes.ObjectName) return L"<unnamed object>";
        UNICODE_STRING name{}; read((ULONG64)attributes.ObjectName, &name, sizeof(name));
        check(name.Length <= 2048 && name.Length % 2 == 0, "bounded diagnostic object name");
        std::wstring value(name.Length / 2, 0);
        if (name.Length) read((ULONG64)name.Buffer, value.data(), name.Length);
        if (attributes.RootDirectory) value = L"<relative to handle " +
            std::to_wstring((ULONG64)attributes.RootDirectory) + L">" + value;
        return value;
    }
    void module(ULONG64 base, const std::wstring& name) {
        IMAGE_DOS_HEADER dos{}; read(base, &dos, sizeof(dos));
        IMAGE_NT_HEADERS64 nt{}; read(base + dos.e_lfanew, &nt, sizeof(nt));
        modules.push_back({base, nt.OptionalHeader.SizeOfImage, fs::path(name).filename().wstring()});
        if (_wcsicmp(fs::path(name).filename().c_str(), L"ntdll.dll") != 0) return;
        for (const char* api : {"NtCreateFile", "NtOpenFile", "NtOpenSection", "NtCreateSection",
                "NtOpenKey", "NtOpenKeyEx", "NtCreateKey", "NtOpenDirectoryObject"}) {
            auto host = GetModuleHandleW(L"ntdll.dll");
            auto function = GetProcAddress(host, api); check(function != nullptr, "fixed trace export");
            breakpoint(base + (ULONG64)function - (ULONG64)host, api);
        }
    }
    static std::string quoted(const std::wstring& text) {
        std::string result;
        for (char c : utf8(text)) {
            if (c == '\\' || c == '"') result += '\\';
            if ((unsigned char)c >= 32) result += c;
        }
        return result;
    }
    bool exception(DWORD tid, const EXCEPTION_RECORD& exception) {
        if (exception.ExceptionCode == EXCEPTION_SINGLE_STEP && stepping.count(tid)) {
            auto step = stepping.at(tid); stepping.erase(tid);
            auto point = points.find(step.address);
            if (point != points.end()) {
                if (!point->second.entry.empty() || !point->second.calls.empty()) byte(step.address, 0xcc);
                else points.erase(point);
            }
            for (HANDLE other : step.paused) { ResumeThread(other); CloseHandle(other); }
            return true;
        }
        auto address = (ULONG64)exception.ExceptionAddress;
        if (exception.ExceptionCode != EXCEPTION_BREAKPOINT || !points.count(address)) return false;
        HANDLE thread = OpenThread(THREAD_GET_CONTEXT | THREAD_SET_CONTEXT, FALSE, tid);
        check(thread != nullptr, "diagnostic thread handle");
        CONTEXT context{}; context.ContextFlags = CONTEXT_FULL;
        check(GetThreadContext(thread, &context), "diagnostic register read");
        auto& point = points.at(address);
        if (!point.entry.empty()) {
            ULONG64 ret = 0; read(context.Rsp, &ret, sizeof(ret));
            Call call{tid, (DWORD)context.Rdx, point.entry, objectName(context.R8), ret, 0, 0};
            if (point.entry == "NtOpenFile") {
                read(context.Rsp + 40, &call.share, sizeof(call.share));
                read(context.Rsp + 48, &call.options, sizeof(call.options));
            }
            breakpoint(ret); points.at(ret).calls.push_back(call);
        } else {
            auto call = std::find_if(point.calls.rbegin(), point.calls.rend(),
                [=](const Call& item) { return item.tid == tid; });
            check(call != point.calls.rend(), "matching diagnostic return thread");
            std::wstring caller = L"unknown"; ULONG64 rva = call->caller;
            for (const auto& m : modules) if (call->caller >= m.base && call->caller < m.base + m.size) {
                caller = m.name; rva = call->caller - m.base; break;
            }
            std::cerr << "{\"trace\":\"" << call->api << "\",\"object\":\"" << quoted(call->name)
                << "\",\"access\":" << call->wanted << ",\"status\":" << (DWORD)context.Rax
                << ",\"caller\":\"" << quoted(caller) << "\",\"caller_rva\":" << rva
                << ",\"share\":" << call->share << ",\"open_options\":" << call->options << "}\n";
            point.calls.erase(std::next(call).base());
        }
        Step step{address, {}};
        for (DWORD other : threads) if (other != tid) {
            HANDLE handle = OpenThread(THREAD_SUSPEND_RESUME, FALSE, other);
            if (handle) {
                check(SuspendThread(handle) != (DWORD)-1, "pause peer during breakpoint step");
                step.paused.push_back(handle);
            }
        }
        stepping.emplace(tid, step);
        byte(address, point.original); context.Rip = address; context.EFlags |= 0x100;
        check(SetThreadContext(thread, &context), "single-step original instruction");
        CloseHandle(thread); return true;
    }
};
