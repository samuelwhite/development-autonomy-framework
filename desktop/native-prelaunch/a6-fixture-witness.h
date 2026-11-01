// A6 fixture corroboration only, after the unchanged snapshot algorithm refuses.
#pragma once
#include "suspended-inspection.h"
#include "handle-diagnostic.h"
namespace a6 {
inline unsigned caseNumber = 0, handleCount = 0, kind = 0;
inline HANDLE intended = nullptr;
inline std::shared_ptr<prelaunch::Handle> intendedPin;
inline uintptr_t originalValue = 0, inheritedValue = 0;
inline FILE_ID_INFO readId{};
inline bool select(const std::wstring& name) {
    if (name == L"A6-12") { caseNumber = 12; handleCount = 4; kind = 6; }
    else if (name == L"A6-13") { caseNumber = 13; handleCount = 4; kind = 1; }
    else if (name == L"A6-14") { caseNumber = 14; handleCount = 3; kind = 7; }
    else return false;
    return true;
}
inline unsigned long long observed(a3::State&, const std::string&);
inline DWORD objectKind(a3::State& s, HANDLE h, const std::string& p) {
    // Bounded type metadata only, never an object's name or memory contents.
    auto query = (NTSTATUS(NTAPI*)(HANDLE, OBJECT_INFORMATION_CLASS, PVOID, ULONG, PULONG))
        GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryObject");
    s.require(query != nullptr, 230);
    alignas(void*) unsigned char data[1024]{}; ULONG returned = 0;
    NTSTATUS status = query(h, ObjectTypeInformation, data, sizeof(data), &returned);
    s.put(p + "type_status", (DWORD)status);
    s.require(status == 0 && returned <= sizeof(data), 231);
    auto text = ((PUBLIC_OBJECT_TYPE_INFORMATION*)data)->TypeName;
    uintptr_t begin = (uintptr_t)text.Buffer, end = begin + text.Length;
    s.require(!(text.Length % sizeof(wchar_t)) && begin >= (uintptr_t)data && end >= begin &&
        end <= (uintptr_t)data + sizeof(data), 232);
    std::wstring name(text.Buffer, text.Length / sizeof(wchar_t));
    if (name == L"Semaphore") return 6;
    s.require(name == L"File", 233);
    DWORD type = GetFileType(h); s.put(p + "file_type", type);
    s.require(type == FILE_TYPE_DISK || type == FILE_TYPE_PIPE, 234);
    return type == FILE_TYPE_PIPE ? 7 : 1;
}
inline void fileWitness(a3::State& s, HANDLE copy, const std::string& p) {
    FILE_ID_INFO id{}; BY_HANDLE_FILE_INFORMATION basic{};
    BOOL ok = GetFileInformationByHandleEx(copy, FileIdInfo, &id, sizeof(id));
    s.put(p + "file_id_ok", ok != FALSE); s.put(p + "file_id_error", ok ? 0 : GetLastError());
    s.require(ok && prelaunch::equal(id, readId), 235);
    unsigned long long halves[2]{}; memcpy(halves, id.FileId.Identifier, sizeof(halves));
    s.put(p + "volume", id.VolumeSerialNumber); s.put(p + "file_low", halves[0]); s.put(p + "file_high", halves[1]);
    BOOL info = GetFileInformationByHandle(copy, &basic);
    bool regular = info && !(basic.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) &&
        basic.nNumberOfLinks == 1 && !basic.nFileSizeHigh && basic.nFileSizeLow == 32;
    s.put(p + "regular_32", regular); s.require(regular, 236);
    SetLastError(ERROR_SUCCESS);
    BOOL same = CompareObjectHandles(copy, s.references[0]);
    DWORD error = same ? 0 : GetLastError();
    s.put(p + "original_object_same", same != FALSE); s.put(p + "original_object_error", error);
    s.require(!same && error == ERROR_NOT_SAME_OBJECT, 237);
}
inline void verifyWitness(a3::State& s, HANDLE pinnedIntended) {
    for (unsigned round = 0; round < 2; ++round) {
        const auto p = "s" + std::to_string(round) + "_";
        s.require(observed(s, p + "entries") == handleCount, 212);
        unsigned pipeSet = 0, extra = 0;
        for (unsigned i = 0; i < handleCount; ++i) {
            const auto e = p + "h" + std::to_string(i) + "_", w = "fixture_" + e;
            auto raw = observed(s, e + "raw"), mask = observed(s, e + "pipes");
            s.require(observed(s, e + "checked") == 255 && !observed(s, e + "hostile"), 213);
            bool isExtra = raw == inheritedValue;
            if (isExtra) { s.require(mask == 0, 214); ++extra; }
            else {
                s.require(mask == 1 || mask == 2 || mask == 4, 215);
                unsigned role = mask == 1 ? 0 : mask == 2 ? 1 : 2;
                s.require(raw == s.pipeValues[role] && !(pipeSet & mask), 216);
                pipeSet |= (unsigned)mask;
            }
            if (originalValue) s.require(raw != originalValue, 217);
            HANDLE out = nullptr;
            BOOL copied = DuplicateHandle(s.process, (HANDLE)raw, GetCurrentProcess(), &out, 0, FALSE, DUPLICATE_SAME_ACCESS);
            s.put(w + "raw", raw); s.put(w + "copy_error", copied ? 0 : GetLastError());
            s.require(copied && out, 219); prelaunch::Handle retained(out);
            unsigned checked = 0, hostile = 0, pipes = 0, matched = 0;
            for (unsigned ref = 0; ref < 9; ++ref) {
                SetLastError(ERROR_SUCCESS);
                BOOL same = CompareObjectHandles(out, ref == 8 ? pinnedIntended : s.references[ref]);
                DWORD error = same ? 0 : GetLastError();
                s.require(same || error == ERROR_NOT_SAME_OBJECT, 220);
                checked |= 1u << ref;
                if (same) {
                    if (ref < 5) hostile |= 1u << ref;
                    else if (ref < 8) pipes |= 1u << (ref - 5);
                    else matched = 1;
                }
            }
            s.put(w + "checked", checked); s.put(w + "hostile", hostile);
            s.put(w + "pipes", pipes); s.put(w + "intended", matched);
            s.require(checked == 511 && !hostile && pipes == mask && matched == isExtra, 221);
            DWORD actualKind = objectKind(s, out, w); s.put(w + "kind", actualKind);
            s.require(actualKind == (isExtra ? kind : 7), 222);
            if (isExtra && caseNumber == 12) {
                DWORD state = WaitForSingleObject(out, 0); s.put(w + "semaphore_wait", state);
                s.require(state == WAIT_TIMEOUT, 223);
            } else if (isExtra && caseNumber == 13) fileWitness(s, out, w);
            else if (isExtra && caseNumber == 14) {
                SetLastError(ERROR_SUCCESS);
                BOOL same = CompareObjectHandles(out, s.references[5]);
                DWORD error = same ? 0 : GetLastError();
                s.put(w + "original_object_same", same != FALSE); s.put(w + "original_object_error", error);
                s.require(!same && error == ERROR_NOT_SAME_OBJECT, 224);
                DWORD available = 0; BOOL peek = PeekNamedPipe(out, nullptr, 0, nullptr, &available, nullptr);
                s.put(w + "peek_ok", peek != FALSE); s.put(w + "available", available);
                s.require(peek && !available, 225);
            }
        }
        s.require(extra == 1 && pipeSet == (caseNumber == 14 ? 6u : 7u), 218);
    }
    s.put("fixture_table_verified", 1);
}
} // namespace a6
