// A7-only supervisor. Expected detector refusal never becomes candidate acceptance.
#pragma once
#include "a7-fixture-mutation.h"
namespace a7 {
struct ControlComplete {};
inline void emit(const char* key, unsigned long long value) {
    std::cerr << "{\"native\":\"a7_" << key << "\",\"value\":" << value << "}\n";
}
inline void control(std::shared_ptr<a3::State> s, std::shared_ptr<Context> c) {
    active = c.get();
    a3::inspect(s); // Exact inspector except the pinned synchronous diagnostic boundary.
    try {
        c->put("shared_passed", s->passed); c->put("shared_inventory_complete", s->inventoryComplete);
        c->put("shared_failure", s->failure);
        c->require(c->boundaryComplete && !c->failure, 327);
        c->require(c->mutation ? (!s->passed && !s->inventoryComplete && s->failure == 120) :
            (s->passed && s->inventoryComplete && !s->failure), 328);
        postWitness(*c);
    } catch (const AuditFailed&) { }
      catch (...) { c->put("unexpected_failure", 1); }
    active = nullptr;
}
[[noreturn]] inline void beforeResume(HANDLE process, HANDLE thread, HANDLE job) {
    auto s = a3::state;
    prelaunch::require(s && s->originalProcess == process && s->originalThread == thread,
        "a7_retained_process_binding");
    a3::emit("inspection_deadline_ms", a3::DeadlineMs); a3::emit("termination_deadline_ms", a3::TerminationMs);
    a3::emit("expected_pid", s->pid); a3::emit("expected_tid", s->tid); a3::emit("expected_creation", s->creation);
    for (unsigned i = 0; i < 3; ++i) a3::emit(("pipe_" + std::to_string(i)).c_str(), s->pipeValues[i]);
    LARGE_INTEGER frequency{}, began{}, inspected{}, stopping{}, terminated{};
    prelaunch::require(QueryPerformanceFrequency(&frequency) && frequency.QuadPart > 0 &&
        QueryPerformanceCounter(&began), "a7_observation_clock");
    emit("qpc_frequency", frequency.QuadPart); emit("tick_unit_ms", 1);
    ULONGLONG start = GetTickCount64();
    auto context = std::make_shared<Context>(s);
    std::thread inspector(control, s, context);
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
    unsigned auditCount = context->published.load(std::memory_order_acquire);
    bool bounded = count + auditCount <= s->rows.size();
    emit("published_rows", count + auditCount); emit("rows_bounded", bounded);
    if (bounded) {
        for (unsigned i = 0; i < count; ++i) a3::emit(s->rows[i].key, s->rows[i].value);
        for (unsigned i = 0; i < auditCount; ++i) emit(context->rows[i].key, context->rows[i].value);
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
    a3::emit("inspection_passed", finished && s->passed);
    bool expected = finished && !expired && clockOK && bounded && context->witnessed && !context->failure &&
        killed && stopped == WAIT_OBJECT_0 && latency <= a3::TerminationMs &&
        exitOK && code == 123 && accounting && !account.ActiveProcesses && memory;
    emit("expected_result_verified", expected);
    if (finished) a3::state.reset();
    if (!expected) throw std::string("a7 detector control failed");
    throw ControlComplete{};
}
} // namespace a7
