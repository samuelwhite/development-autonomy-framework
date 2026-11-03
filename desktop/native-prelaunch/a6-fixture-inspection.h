// A6-only supervisor. Expected detector refusal never becomes candidate acceptance.
#pragma once
#include "a6-fixture-witness.h"
namespace a6 {
struct ControlComplete {};
inline void emit(const char* key, unsigned long long value) {
    std::cerr << "{\"native\":\"a6_" << key << "\",\"value\":" << value << "}\n";
}
inline unsigned long long observed(a3::State& s, const std::string& key) {
    unsigned count = s.published.load(std::memory_order_acquire), matches = 0;
    unsigned long long value = 0;
    for (unsigned i = 0; i < count; ++i) if (key == s.rows[i].key) { ++matches; value = s.rows[i].value; }
    s.require(matches == 1, 210); return value;
}
inline void control(std::shared_ptr<a3::State> s, std::shared_ptr<prelaunch::Handle> pinnedIntended) {
    a3::inspect(s); // The SAME inspector and unchanged three-pipe acceptance policy.
    try {
        s->require(s->inventoryComplete && !s->passed && s->failure == 116, 211);
        verifyWitness(*s, pinnedIntended->h);
        a3::identity(*s, "fixture_final_");
        s->put("fixture_witness_complete", 1);
    } catch (const a3::Failed&) { }
      catch (...) { s->put("fixture_unexpected_failure", 1); }
}
[[noreturn]] inline void beforeResume(HANDLE process, HANDLE thread, HANDLE job) {
    auto s = a3::state;
    prelaunch::require(s && s->originalProcess == process && s->originalThread == thread,
        "a6_retained_process_binding");
    a3::emit("inspection_deadline_ms", a3::DeadlineMs); a3::emit("termination_deadline_ms", a3::TerminationMs);
    a3::emit("expected_pid", s->pid); a3::emit("expected_tid", s->tid); a3::emit("expected_creation", s->creation);
    for (unsigned i = 0; i < 3; ++i) a3::emit(("pipe_" + std::to_string(i)).c_str(), s->pipeValues[i]);
    LARGE_INTEGER frequency{}, began{}, inspected{}, stopping{}, terminated{};
    prelaunch::require(QueryPerformanceFrequency(&frequency) && frequency.QuadPart > 0 &&
        QueryPerformanceCounter(&began), "a6_observation_clock");
    emit("qpc_frequency", frequency.QuadPart); emit("tick_unit_ms", 1);
    ULONGLONG start = GetTickCount64();
    std::thread inspector(control, s, intendedPin);
    DWORD wait = WaitForSingleObject(inspector.native_handle(), a3::DeadlineMs);
    ULONGLONG elapsed = GetTickCount64() - start;
    BOOL inspectionClock = QueryPerformanceCounter(&inspected);
    bool finished = wait == WAIT_OBJECT_0, expired = elapsed >= a3::DeadlineMs;
    if (!finished || expired) s->stop.store(true);
    BOOL stopClock = QueryPerformanceCounter(&stopping);
    ULONGLONG killing = GetTickCount64();
    BOOL killed = TerminateJobObject(job, 123); DWORD error = killed ? 0 : GetLastError();
    DWORD stopped = WaitForSingleObject(process, a3::TerminationMs);
    ULONGLONG latency = GetTickCount64() - killing;
    BOOL terminationClock = QueryPerformanceCounter(&terminated);
    bool clockOK = inspectionClock && stopClock && terminationClock &&
        inspected.QuadPart >= began.QuadPart && stopping.QuadPart >= inspected.QuadPart &&
        terminated.QuadPart >= stopping.QuadPart;
    emit("qpc_queries_ok", clockOK);
    emit("inspection_qpc_ticks", clockOK ? inspected.QuadPart - began.QuadPart : 0);
    emit("termination_qpc_ticks", clockOK ? terminated.QuadPart - stopping.QuadPart : 0);
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
    bool expected = finished && !expired && clockOK && witnessed && s->inventoryComplete && !s->passed &&
        s->failure == 116 && killed && stopped == WAIT_OBJECT_0 && latency <= a3::TerminationMs &&
        exitOK && code == 123 && accounting && !account.ActiveProcesses && memory;
    emit("expected_refusal_verified", expected);
    if (finished) a3::state.reset();
    if (!expected) throw std::string("a6 detector control failed");
    throw ControlComplete{};
}
} // namespace a6
