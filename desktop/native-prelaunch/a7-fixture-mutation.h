// Diagnostic-only boundary. No shared inspector state or policy is rewritten.
#pragma once
#include "identity.h"
namespace a3 { struct Inventory; }
namespace a7 { inline void boundary(const a3::Inventory&); }
#include "a7-suspended-inspection.generated.h"
namespace a7 {
struct AuditFailed {};
inline unsigned sequence = 0;
inline bool select(const std::wstring& name) {
    if (name == L"A7-C0") sequence = 1;
    else if (name == L"A7-15") sequence = 2;
    else return false;
    return true;
}
struct Context {
    std::shared_ptr<a3::State> owner;
    std::array<a3::Row, 128> rows{};
    std::atomic<unsigned> published{0};
    unsigned calls = 0, inward = 0, failure = 0;
    uintptr_t target = 0;
    bool mutation = false, boundaryComplete = false, witnessed = false;
    explicit Context(std::shared_ptr<a3::State> s) : owner(s), mutation(sequence == 2) {}
    void put(const std::string& key, unsigned long long value) {
        unsigned n = published.load(std::memory_order_relaxed);
        if (n >= rows.size() || key.size() >= sizeof(rows[n].key)) throw AuditFailed{};
        memcpy(rows[n].key, key.c_str(), key.size() + 1); rows[n].value = value;
        published.store(n + 1, std::memory_order_release);
    }
    void require(bool ok, unsigned code) {
        if (owner->stop.load()) { ok = false; code = 399; }
        if (!ok) { if (!failure) { failure = code; put("audit_failure", code); } throw AuditFailed{}; }
    }
    void tick(const char* key) {
        LARGE_INTEGER now{}; require(QueryPerformanceCounter(&now) && now.QuadPart >= 0, 301);
        put(key, now.QuadPart);
    }
    void identity(const std::string& p) {
        auto& s = *owner;
        DWORD pid = GetProcessId(s.process), tid = GetThreadId(s.thread), owning = GetProcessIdOfThread(s.thread);
        FILETIME created{}, exited{}, kernel{}, user{};
        BOOL ok = GetProcessTimes(s.process, &created, &exited, &kernel, &user);
        DWORD error = ok ? 0 : GetLastError(), wait = WaitForSingleObject(s.process, 0);
        put(p + "pid", pid); put(p + "tid", tid); put(p + "thread_owner", owning);
        put(p + "creation", a3::timeValue(created)); put(p + "times_error", error); put(p + "process_wait", wait);
        require(pid == s.pid && tid == s.tid && owning == s.pid && ok &&
            a3::timeValue(created) == s.creation && wait == WAIT_TIMEOUT, 302);
    }
    void count(const std::string& p, DWORD expected) {
        DWORD value = 0; BOOL ok = GetProcessHandleCount(owner->process, &value);
        put(p + "ok", ok != FALSE); put(p + "value", value);
        require(ok && value == expected, 303);
    }
    unsigned long long observed(const std::string& key) {
        unsigned count = owner->published.load(std::memory_order_acquire), matches = 0;
        unsigned long long value = 0;
        for (unsigned n = 0; n < count; ++n) if (key == owner->rows[n].key) {
            ++matches; value = owner->rows[n].value;
        }
        require(matches == 1, 304); return value;
    }
    void witness(uintptr_t raw, DWORD expectedHostile, DWORD expectedPipe, const std::string& p) {
        HANDLE local = nullptr;
        require(raw && raw != (uintptr_t)INVALID_HANDLE_VALUE, 305);
        BOOL ok = DuplicateHandle(owner->process, (HANDLE)raw, GetCurrentProcess(), &local,
            0, FALSE, DUPLICATE_SAME_ACCESS);
        put(p + "raw", raw); put(p + "copy_ok", ok != FALSE); put(p + "copy_error", ok ? 0 : GetLastError());
        require(ok && local, 306); prelaunch::Handle pin(local);
        DWORD checked = 0, hostile = 0, pipes = 0;
        for (unsigned r = 0; r < 8; ++r) {
            SetLastError(ERROR_SUCCESS);
            BOOL same = CompareObjectHandles(local, owner->references[r]);
            DWORD error = same ? 0 : GetLastError();
            require(same || error == ERROR_NOT_SAME_OBJECT, 307);
            checked |= 1u << r;
            if (same) { if (r < 5) hostile |= 1u << r; else pipes |= 1u << (r - 5); }
        }
        put(p + "checked", checked); put(p + "hostile", hostile); put(p + "pipes", pipes);
        require(checked == 255 && hostile == expectedHostile && pipes == expectedPipe, 308);
        // Type/access queries occur only AFTER exact identity against retained objects.
        auto query = (NTSTATUS(NTAPI*)(HANDLE, OBJECT_INFORMATION_CLASS, PVOID, ULONG, PULONG))
            GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryObject");
        require(query != nullptr, 309);
        alignas(void*) unsigned char data[1024]{}; ULONG returned = 0;
        NTSTATUS status = query(local, ObjectTypeInformation, data, sizeof(data), &returned);
        put(p + "type_status", (DWORD)status); put(p + "type_bytes", returned);
        require(status == 0 && returned >= sizeof(PUBLIC_OBJECT_TYPE_INFORMATION) && returned <= sizeof(data), 310);
        auto name = ((PUBLIC_OBJECT_TYPE_INFORMATION*)data)->TypeName;
        uintptr_t begin = (uintptr_t)name.Buffer, end = begin + name.Length;
        require(!(name.Length % sizeof(wchar_t)) && begin >= (uintptr_t)data && end >= begin &&
            end <= (uintptr_t)data + returned, 311);
        std::wstring type(name.Buffer, name.Length / sizeof(wchar_t));
        require(type == (expectedHostile ? L"Event" : L"File"), 312);
        put(p + "kind", expectedHostile ? 3 : 7);
        if (expectedHostile) {
            PUBLIC_OBJECT_BASIC_INFORMATION basic{}; returned = 0;
            status = query(local, ObjectBasicInformation, &basic, sizeof(basic), &returned);
            put(p + "basic_status", (DWORD)status); put(p + "basic_bytes", returned);
            put(p + "access", basic.GrantedAccess);
            require(status == 0 && returned == sizeof(basic) && basic.GrantedAccess == SYNCHRONIZE, 313);
            DWORD wait = WaitForSingleObject(local, 0); put(p + "event_wait", wait);
            require(wait == WAIT_TIMEOUT, 314);
        } else {
            DWORD typeValue = GetFileType(local); put(p + "file_type", typeValue);
            require(typeValue == FILE_TYPE_PIPE, 315);
        }
    }
};
inline thread_local Context* active = nullptr;
inline void boundary(const a3::Inventory& first) {
    if (!active) throw AuditFailed{};
    auto& c = *active;
    c.require(++c.calls == 1, 316); c.put("boundary_calls", c.calls);
    c.tick("boundary_begin_qpc"); c.identity("boundary_");
    c.require(first.values.size() == 3 && first.pipes.size() == 3 && first.hostile.size() == 3, 317);
    unsigned masks = 0;
    for (unsigned i = 0; i < 3; ++i) {
        DWORD mask = first.pipes[i];
        c.require(!first.hostile[i] && (mask == 1 || mask == 2 || mask == 4) && !(masks & mask), 318);
        unsigned role = mask == 1 ? 0 : mask == 2 ? 1 : 2;
        c.require(first.values[i] == c.owner->pipeValues[role], 319); masks |= mask;
    }
    c.count("boundary_before_", 3);
    DWORD event = WaitForSingleObject(c.owner->references[3], 0); c.put("event_before", event);
    c.require(event == WAIT_TIMEOUT, 320);
    c.put("requested_access", c.mutation ? SYNCHRONIZE : 0);
    c.put("requested_inherit", 0); c.put("requested_options", 0);
    if (c.mutation) {
        c.require(!c.inward, 321); ++c.inward; c.put("inward_attempts", c.inward);
        c.tick("inward_begin_qpc"); c.require(!c.owner->stop.load(), 399);
        HANDLE target = nullptr;
        // THE ONLY INWARD DUPLICATION. Exact owned child, existing event, reduced rights.
        BOOL ok = DuplicateHandle(GetCurrentProcess(), c.owner->references[3], c.owner->process,
            &target, SYNCHRONIZE, FALSE, 0);
        DWORD error = ok ? 0 : GetLastError();
        c.put("inward_ok", ok != FALSE); c.put("inward_error", error);
        c.target = (uintptr_t)target; c.put("target", c.target);
        c.tick("inward_end_qpc");
        c.require(ok && target && target != INVALID_HANDLE_VALUE, 322);
        c.require(std::find(first.values.begin(), first.values.end(), c.target) == first.values.end(), 323);
    } else { c.put("inward_attempts", 0); c.put("target", 0); }
    c.count("boundary_after_", c.mutation ? 4 : 3);
    if (c.mutation) c.witness(c.target, 8, 0, "boundary_w_");
    c.tick("boundary_end_qpc"); c.boundaryComplete = true; c.put("boundary_complete", 1);
}
inline void postWitness(Context& c) {
    c.count("post_count_", c.mutation ? 4 : 3);
    std::set<uintptr_t> expected(c.owner->pipeValues, c.owner->pipeValues + 3), found;
    if (c.mutation) expected.insert(c.target);
    for (unsigned n = 0; n < (c.mutation ? 4u : 3u); ++n) {
        const auto key = "s1_h" + std::to_string(n) + "_";
        auto raw = (uintptr_t)c.observed(key + "raw");
        c.require(found.insert(raw).second && expected.count(raw), 324);
        DWORD hostile = raw == c.target ? 8 : 0, pipe = 0;
        for (unsigned i = 0; i < 3; ++i) if (raw == c.owner->pipeValues[i]) pipe = 1u << i;
        c.require(c.observed(key + "checked") == 255 && c.observed(key + "hostile") == hostile &&
            c.observed(key + "pipes") == pipe, 325);
        c.witness(raw, hostile, pipe, "post_h" + std::to_string(n) + "_");
    }
    c.require(found == expected, 326); c.identity("post_");
    c.tick("post_end_qpc"); c.witnessed = true; c.put("witness_complete", 1);
}
} // namespace a7
