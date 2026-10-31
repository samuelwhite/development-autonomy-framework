// A4-only supervisor. Expected detector refusal never becomes candidate acceptance.
#pragma once
#include "suspended-inspection.h"
namespace a4 {
struct ControlComplete {};
inline unsigned caseNumber = 0;
inline uintptr_t originalValue = 0, inheritedValue = 0;
inline FILE_ID_INFO originalId{};
inline void emit(const char* key, unsigned long long value) {
    std::cerr << "{\"native\":\"a4_" << key << "\",\"value\":" << value << "}\n";
}
inline unsigned long long observed(a3::State& s, const std::string& key) {
    unsigned count = s.published.load(std::memory_order_acquire), matches = 0;
    unsigned long long value = 0;
    for (unsigned i = 0; i < count; ++i) if (key == s.rows[i].key) { ++matches; value = s.rows[i].value; }
    s.require(matches == 1, 210); return value;
}
inline void control(std::shared_ptr<a3::State> s) {
    a3::inspect(s); // The SAME inspector and unchanged three-pipe acceptance policy.
    try {
        s->require(s->inventoryComplete && !s->passed && s->failure == 201, 211);
        for (unsigned round = 0; round < 2; ++round) {
            const auto p = "s" + std::to_string(round) + "_";
            s->require(observed(*s, p + "entries") == 4, 212);
            unsigned hostile = 0, pipes = 0;
            for (unsigned i = 0; i < 4; ++i) {
                const auto e = p + "h" + std::to_string(i) + "_";
                auto raw = observed(*s, e + "raw"), h = observed(*s, e + "hostile"), pipe = observed(*s, e + "pipes");
                s->require(observed(*s, e + "checked") == 255, 213);
                if (h) { s->require(h == 1 && pipe == 0 && raw == inheritedValue, 214); ++hostile; }
                else {
                    s->require(pipe == 1 || pipe == 2 || pipe == 4, 215);
                    unsigned stream = pipe == 1 ? 0 : pipe == 2 ? 1 : 2;
                    s->require(raw == s->pipeValues[stream] && !(pipes & pipe), 216);
                    pipes |= (unsigned)pipe;
                }
                if (caseNumber == 2) s->require(raw != originalValue, 217);
            }
            s->require(hostile == 1 && pipes == 7, 218);
        }
        s->put("fixture_table_verified", 1);
        // A separate outward duplication witnesses actual inheritance independently
        // of the PSS walk. It never probes the absent original slot in alias mode.
        HANDLE copy = nullptr;
        BOOL ok = DuplicateHandle(s->process, (HANDLE)inheritedValue, GetCurrentProcess(),
            &copy, 0, FALSE, DUPLICATE_SAME_ACCESS);
        s->put("fixture_copy_error", ok ? 0 : GetLastError());
        s->require(ok && copy, 219);
        prelaunch::Handle retained(copy);
        SetLastError(ERROR_SUCCESS);
        BOOL same = CompareObjectHandles(copy, s->references[0]);
        s->put("fixture_object_same", same != FALSE);
        s->put("fixture_object_error", same ? 0 : GetLastError());
        s->require(same, 220);
        FILE_ID_INFO file{};
        BOOL id = GetFileInformationByHandleEx(copy, FileIdInfo, &file, sizeof(file));
        s->put("fixture_file_id_ok", id != FALSE);
        s->put("fixture_file_id_error", id ? 0 : GetLastError());
        s->require(id, 221);
        unsigned long long halves[2]{}; memcpy(halves, file.FileId.Identifier, sizeof(halves));
        s->put("fixture_volume", file.VolumeSerialNumber);
        s->put("fixture_file_low", halves[0]); s->put("fixture_file_high", halves[1]);
        s->require(prelaunch::equal(file, originalId), 222);
        a3::identity(*s, "fixture_final_");
        s->put("fixture_witness_complete", 1);
    } catch (const a3::Failed&) { }
      catch (...) { s->put("fixture_unexpected_failure", 1); }
}
[[noreturn]] inline void beforeResume(HANDLE process, HANDLE thread, HANDLE job) {
    auto s = a3::state;
    prelaunch::require(s && s->originalProcess == process && s->originalThread == thread,
        "a4_retained_process_binding");
    a3::emit("inspection_deadline_ms", a3::DeadlineMs); a3::emit("termination_deadline_ms", a3::TerminationMs);
    a3::emit("expected_pid", s->pid); a3::emit("expected_tid", s->tid); a3::emit("expected_creation", s->creation);
    for (unsigned i = 0; i < 3; ++i) a3::emit(("pipe_" + std::to_string(i)).c_str(), s->pipeValues[i]);
    ULONGLONG start = GetTickCount64();
    std::thread inspector(control, s);
    DWORD wait = WaitForSingleObject(inspector.native_handle(), a3::DeadlineMs);
    ULONGLONG elapsed = GetTickCount64() - start;
    bool finished = wait == WAIT_OBJECT_0, expired = elapsed >= a3::DeadlineMs;
    if (!finished || expired) s->stop.store(true);
    ULONGLONG killing = GetTickCount64();
    BOOL killed = TerminateJobObject(job, 123); DWORD error = killed ? 0 : GetLastError();
    DWORD stopped = WaitForSingleObject(process, a3::TerminationMs);
    ULONGLONG latency = GetTickCount64() - killing;
    if (finished) inspector.join(); else inspector.detach();
    a3::emit("inspection_elapsed_ms", elapsed); a3::emit("deadline_expired", expired || !finished);
    a3::emit("inspector_wait", wait); a3::emit("inspector_finished", finished);
    a3::emit("last_stage", s->stage.load()); a3::emit("terminate_job_ok", killed != FALSE);
    a3::emit("terminate_job_error", error); a3::emit("process_wait", stopped);
    a3::emit("termination_elapsed_ms", latency);
    unsigned count = s->published.load(std::memory_order_acquire);
    bool witnessed = false;
    for (unsigned i = 0; i < count; ++i) {
        a3::emit(s->rows[i].key, s->rows[i].value);
        if (std::string(s->rows[i].key) == "fixture_witness_complete" && s->rows[i].value == 1) witnessed = true;
    }
    DWORD code = 0; BOOL exitOK = GetExitCodeProcess(process, &code);
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION account{};
    BOOL accounting = QueryInformationJobObject(job, JobObjectBasicAccountingInformation, &account, sizeof(account), nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    BOOL memory = QueryInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits), nullptr);
    a3::emit("exit_query_ok", exitOK != FALSE); a3::emit("child_exit", code);
    a3::emit("accounting_ok", accounting != FALSE); a3::emit("active_processes", account.ActiveProcesses);
    a3::emit("user_cpu_100ns", account.TotalUserTime.QuadPart); a3::emit("memory_query_ok", memory != FALSE);
    a3::emit("peak_memory_bytes", limits.PeakProcessMemoryUsed); a3::emit("child_resumed", 0);
    a3::emit("inspection_passed", 0); // The candidate policy REFUSED the child.
    bool expected = finished && !expired && witnessed && s->inventoryComplete && !s->passed &&
        s->failure == 201 && killed && stopped == WAIT_OBJECT_0 && latency <= a3::TerminationMs &&
        exitOK && code == 123 && accounting && !account.ActiveProcesses && memory;
    emit("expected_refusal_verified", expected);
    if (finished) a3::state.reset();
    if (!expected) throw std::string("a4 detector control failed");
    throw ControlComplete{};
}
} // namespace a4
