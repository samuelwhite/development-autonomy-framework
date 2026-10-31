// Suspended inspection only. No resume, policy mutation, memory capture or admission.
#pragma once
#include "identity.h"
#include <processsnapshot.h>
#include <array>
#include <atomic>
#include <thread>
#include <set>
#include <cstdio>
#include <iostream>
#include <algorithm>
#pragma comment(lib, "onecore.lib")
namespace a3 {
constexpr DWORD DeadlineMs = 5000, TerminationMs = 3000, MaxHandles = 16;
constexpr DWORD CaptureFlags = PSS_CAPTURE_HANDLES | PSS_CAPTURE_THREADS;
struct FeasibilityComplete {};
struct Failed {};
struct Row { char key[80]{}; unsigned long long value = 0; };
struct State {
    std::array<Row, 384> rows{};
    std::atomic<unsigned> published{0}, stage{0};
    std::atomic<bool> stop{false}, done{false};
    bool passed = false;
    bool inventoryComplete = false;
    unsigned failure = 0;
    DWORD pid = 0, tid = 0;
    ULONGLONG creation = 0;
    HANDLE process = nullptr, thread = nullptr;
    HANDLE originalProcess = nullptr, originalThread = nullptr;
    HANDLE references[8]{}; // five hostile objects, then three original pipes
    uintptr_t pipeValues[3]{};
    ~State() {
        for (HANDLE h : references) if (h) CloseHandle(h);
        if (thread) CloseHandle(thread);
        if (process) CloseHandle(process);
    }
    void put(const std::string& key, unsigned long long value) {
        unsigned n = published.load(std::memory_order_relaxed);
        if (n >= rows.size() || key.size() >= sizeof(rows[n].key)) throw Failed{};
        memcpy(rows[n].key, key.c_str(), key.size() + 1); rows[n].value = value;
        published.store(n + 1, std::memory_order_release);
    }
    void require(bool ok, unsigned code) {
        if (!ok) { failure = code; put("failure", code); throw Failed{}; }
        if (stop.load()) throw Failed{};
    }
};
inline ULONGLONG timeValue(FILETIME t) { return ((ULONGLONG)t.dwHighDateTime << 32) | t.dwLowDateTime; }
inline HANDLE retain(HANDLE h) {
    HANDLE copy = nullptr;
    prelaunch::require(DuplicateHandle(GetCurrentProcess(), h, GetCurrentProcess(), &copy,
        0, FALSE, DUPLICATE_SAME_ACCESS), "a3_retain_owned_reference");
    return copy;
}
inline std::shared_ptr<State> state;
inline void emit(const char* key, unsigned long long value) {
    std::cerr << "{\"native\":\"a3_" << key << "\",\"value\":" << value << "}\n";
}
inline void identity(State& s, const std::string& p) {
    s.stage.store(1);
    DWORD pid = GetProcessId(s.process), tid = GetThreadId(s.thread);
    DWORD owner = GetProcessIdOfThread(s.thread);
    FILETIME created{}, exited{}, kernel{}, user{};
    BOOL times = GetProcessTimes(s.process, &created, &exited, &kernel, &user);
    DWORD error = times ? 0 : GetLastError();
    DWORD wait = WaitForSingleObject(s.process, 0);
    s.put(p + "pid", pid); s.put(p + "tid", tid); s.put(p + "thread_owner", owner);
    s.put(p + "creation", timeValue(created)); s.put(p + "times_error", error);
    s.put(p + "process_wait", wait);
    s.require(pid == s.pid && tid == s.tid && owner == s.pid && times &&
        timeValue(created) == s.creation && wait == WAIT_TIMEOUT, 101);
}
inline void policy(State& s, const std::string& p) {
    s.stage.store(2);
    PROCESS_MITIGATION_STRICT_HANDLE_CHECK_POLICY policy{};
    BOOL ok = GetProcessMitigationPolicy(s.process, ProcessStrictHandleCheckPolicy, &policy, sizeof(policy));
    DWORD error = ok ? 0 : GetLastError();
    s.put(p + "policy_ok", ok != FALSE); s.put(p + "policy_error", error);
    s.put(p + "policy_flags", policy.Flags);
    s.put(p + "policy_raise", policy.RaiseExceptionOnInvalidHandleReference);
    s.put(p + "policy_permanent", policy.HandleExceptionsPermanentlyEnabled);
    // Do not enable a missing policy or reinterpret an unsupported observation.
    s.require(ok && policy.Flags == 3 && policy.RaiseExceptionOnInvalidHandleReference &&
        policy.HandleExceptionsPermanentlyEnabled, 102);
}
struct Snapshot {
    HPSS snapshot = nullptr;
    HPSSWALK handles = nullptr, threads = nullptr;
    ~Snapshot() {
        if (handles) PssWalkMarkerFree(handles);
        if (threads) PssWalkMarkerFree(threads);
        if (snapshot) PssFreeSnapshot(GetCurrentProcess(), snapshot);
    }
    void release(State& s, const std::string& p) {
        s.stage.store(8);
        DWORD h = PssWalkMarkerFree(handles); handles = nullptr;
        DWORD t = PssWalkMarkerFree(threads); threads = nullptr;
        DWORD snap = PssFreeSnapshot(GetCurrentProcess(), snapshot); snapshot = nullptr;
        s.put(p + "handle_marker_free", h); s.put(p + "thread_marker_free", t);
        s.put(p + "snapshot_free", snap); s.require(!h && !t && !snap, 108);
    }
};
struct Inventory {
    std::vector<uintptr_t> values;
    std::vector<std::unique_ptr<prelaunch::Handle>> retained;
    std::vector<DWORD> pipes, hostile;
};
inline Inventory snapshot(State& s, unsigned round) {
    const auto p = "s" + std::to_string(round) + "_";
    identity(s, p);
    DWORD before = 0;
    BOOL countOK = GetProcessHandleCount(s.process, &before);
    s.put(p + "count_before_ok", countOK != FALSE); s.put(p + "count_before", before);
    s.require(countOK && before && before <= MaxHandles, 103);
    Snapshot snap; s.stage.store(3);
    DWORD status = PssCaptureSnapshot(s.process, (PSS_CAPTURE_FLAGS)CaptureFlags, 0, &snap.snapshot);
    s.put(p + "capture_status", status); s.require(status == ERROR_SUCCESS && snap.snapshot, 104);
    PSS_HANDLE_INFORMATION hi{}; PSS_THREAD_INFORMATION ti{};
    DWORD hs = PssQuerySnapshot(snap.snapshot, PSS_QUERY_HANDLE_INFORMATION, &hi, sizeof(hi));
    DWORD ts = PssQuerySnapshot(snap.snapshot, PSS_QUERY_THREAD_INFORMATION, &ti, sizeof(ti));
    s.put(p + "handle_query_status", hs); s.put(p + "thread_query_status", ts);
    s.put(p + "handles_captured", hi.HandlesCaptured); s.put(p + "threads_captured", ti.ThreadsCaptured);
    s.require(!hs && !ts && hi.HandlesCaptured == before && hi.HandlesCaptured <= MaxHandles &&
        ti.ThreadsCaptured == 1 && ti.ContextLength == 0, 105);
    s.stage.store(4);
    DWORD hm = PssWalkMarkerCreate(nullptr, &snap.handles);
    DWORD tm = PssWalkMarkerCreate(nullptr, &snap.threads);
    s.put(p + "handle_marker_status", hm); s.put(p + "thread_marker_status", tm);
    s.require(!hm && !tm, 106);
    PSS_THREAD_ENTRY te{};
    DWORD tw = PssWalkSnapshot(snap.snapshot, PSS_WALK_THREADS, snap.threads, &te, sizeof(te));
    s.put(p + "thread_walk_status", tw); s.put(p + "thread_pid", te.ProcessId);
    s.put(p + "thread_tid", te.ThreadId); s.put(p + "suspend_count", te.SuspendCount);
    s.put(p + "thread_exit", te.ExitStatus); s.put(p + "context_bytes", te.SizeOfContextRecord);
    s.require(!tw && te.ProcessId == s.pid && te.ThreadId == s.tid && te.SuspendCount == 1 &&
        te.ExitStatus == STILL_ACTIVE && te.SizeOfContextRecord == 0, 107);
    DWORD endThread = PssWalkSnapshot(snap.snapshot, PSS_WALK_THREADS, snap.threads, &te, sizeof(te));
    s.put(p + "thread_end", endThread); s.require(endThread == ERROR_NO_MORE_ITEMS, 109);
    Inventory found; std::set<uintptr_t> unique;
    DWORD end = 0;
    for (DWORD n = 0; n <= MaxHandles; ++n) {
        PSS_HANDLE_ENTRY he{}; s.stage.store(5);
        DWORD walked = PssWalkSnapshot(snap.snapshot, PSS_WALK_HANDLES, snap.handles, &he, sizeof(he));
        if (walked == ERROR_NO_MORE_ITEMS) { end = walked; break; }
        s.require(!walked && n < MaxHandles && he.Handle && he.Handle != INVALID_HANDLE_VALUE, 110);
        const auto e = p + "h" + std::to_string(n) + "_";
        s.put(e + "raw", (uintptr_t)he.Handle);
        s.require(unique.insert((uintptr_t)he.Handle).second, 111);
        HANDLE out = nullptr; s.stage.store(6);
        BOOL copied = DuplicateHandle(s.process, he.Handle, GetCurrentProcess(), &out, 0, FALSE, DUPLICATE_SAME_ACCESS);
        DWORD copyError = copied ? 0 : GetLastError();
        s.put(e + "copy_error", copyError); s.require(copied && out, 112);
        found.retained.push_back(std::make_unique<prelaunch::Handle>(out));
        found.values.push_back((uintptr_t)he.Handle);
        DWORD hostile = 0, pipes = 0, checked = 0;
        for (unsigned ref = 0; ref < 8; ++ref) {
            s.stage.store(7); SetLastError(ERROR_SUCCESS);
            BOOL same = CompareObjectHandles(out, s.references[ref]);
            DWORD comparison = same ? ERROR_SUCCESS : GetLastError();
            if (same || comparison == ERROR_NOT_SAME_OBJECT) checked |= 1u << ref;
            else { s.put(e + "bad_compare_ref", ref); s.put(e + "bad_compare_error", comparison); }
            if (same) { if (ref < 5) hostile |= 1u << ref; else pipes |= 1u << (ref - 5); }
        }
        s.put(e + "checked", checked); s.put(e + "hostile", hostile); s.put(e + "pipes", pipes);
        s.require(checked == 255, 113); found.pipes.push_back(pipes); found.hostile.push_back(hostile);
        // Complete the bounded table before interpreting unknown/hostile objects.
    }
    s.put(p + "handle_end", end); s.put(p + "entries", found.values.size());
    DWORD after = 0; BOOL afterOK = GetProcessHandleCount(s.process, &after);
    s.put(p + "count_after_ok", afterOK != FALSE); s.put(p + "count_after", after);
    s.require(end == ERROR_NO_MORE_ITEMS && found.values.size() == hi.HandlesCaptured &&
        afterOK && before == after, 114);
    snap.release(s, p);
    policy(s, p);
    return found;
}
inline void requireAccepted(State& s, const Inventory& found) {
    // Identity refusal precedes count refusal, after COMPLETE inventories. There
    // is no fixture exception: the accepted-object policy remains three pipes.
    for (DWORD mask : found.hostile) s.require(mask == 0, 201);
    // Any unknown object or extra alias is refused, even when it has reduced rights.
    s.require(found.values.size() == 3, 115);
    std::set<DWORD> pipeSet;
    for (unsigned n = 0; n < found.values.size(); ++n) {
        DWORD mask = found.pipes[n];
        s.require(mask == 1 || mask == 2 || mask == 4, 116);
        s.require(pipeSet.insert(mask).second, 117);
        unsigned stream = mask == 1 ? 0 : mask == 2 ? 1 : 2;
        s.require(found.values[n] == s.pipeValues[stream], 118);
        for (unsigned ref = 0; ref < 5; ++ref) {
            SetLastError(ERROR_SUCCESS);
            BOOL same = CompareObjectHandles(found.retained[n]->h, s.references[ref]);
            s.require(!same && GetLastError() == ERROR_NOT_SAME_OBJECT, 119);
        }
    }
}
inline void inspect(std::shared_ptr<State> s) {
    try {
        s->put("capture_flags", CaptureFlags); s->put("context_flags", 0);
        auto first = snapshot(*s, 0), second = snapshot(*s, 1);
        std::set<uintptr_t> a(first.values.begin(), first.values.end()), b(second.values.begin(), second.values.end());
        s->require(a == b, 120);
        for (unsigned i = 0; i < first.values.size(); ++i) {
            auto at = std::find(second.values.begin(), second.values.end(), first.values[i]) - second.values.begin();
            s->require(CompareObjectHandles(first.retained[i]->h, second.retained[at]->h), 121);
        }
        identity(*s, "final_"); s->put("inventories_consistent", 1);
        s->inventoryComplete = true;
        requireAccepted(*s, first); requireAccepted(*s, second);
        s->passed = true;
    } catch (const Failed&) { /* Refusal is retained; never a successful observation. */ }
      catch (...) { s->put("failure", 199); }
    s->done.store(true, std::memory_order_release);
}
inline void beforeResume(HANDLE process, HANDLE thread, HANDLE job) {
    prelaunch::require(state && state->originalProcess == process &&
        state->originalThread == thread, "a3_retained_process_binding");
    emit("inspection_deadline_ms", DeadlineMs); emit("termination_deadline_ms", TerminationMs);
    emit("expected_pid", state->pid); emit("expected_tid", state->tid); emit("expected_creation", state->creation);
    for (unsigned i = 0; i < 3; ++i) emit(("pipe_" + std::to_string(i)).c_str(), state->pipeValues[i]);
    ULONGLONG start = GetTickCount64();
    std::thread inspector(inspect, state);
    // The supervisor never enters a snapshot, duplication or comparison call.
    DWORD inspectorWait = WaitForSingleObject(inspector.native_handle(), DeadlineMs);
    const ULONGLONG elapsed = GetTickCount64() - start;
    const bool finished = inspectorWait == WAIT_OBJECT_0 && state->done.load(std::memory_order_acquire);
    const bool deadline = elapsed >= DeadlineMs;
    if (!finished || deadline) state->stop.store(true);
    // Case 01 NEVER resumes the child, including after a successful inspection.
    ULONGLONG killing = GetTickCount64();
    BOOL killed = TerminateJobObject(job, 123); DWORD killError = killed ? 0 : GetLastError();
    DWORD waited = WaitForSingleObject(process, TerminationMs);
    ULONGLONG latency = GetTickCount64() - killing;
    if (finished) inspector.join();
    else inspector.detach(); // Owns its state/references until return or helper-process exit.
    emit("inspection_elapsed_ms", elapsed); emit("deadline_expired", deadline || !finished);
    emit("inspector_wait", inspectorWait);
    emit("inspector_finished", finished); emit("last_stage", state->stage.load());
    emit("terminate_job_ok", killed != FALSE); emit("terminate_job_error", killError);
    emit("process_wait", waited); emit("termination_elapsed_ms", latency);
    unsigned count = state->published.load(std::memory_order_acquire);
    // Published rows are immutable. A detached inspector can only append new rows.
    for (unsigned i = 0; i < count; ++i) emit(state->rows[i].key, state->rows[i].value);
    DWORD code = 0; BOOL exitOK = GetExitCodeProcess(process, &code);
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION account{};
    BOOL accounting = QueryInformationJobObject(job, JobObjectBasicAccountingInformation, &account, sizeof(account), nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    BOOL memory = QueryInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits), nullptr);
    emit("exit_query_ok", exitOK != FALSE); emit("child_exit", code);
    emit("accounting_ok", accounting != FALSE); emit("active_processes", account.ActiveProcesses);
    emit("user_cpu_100ns", account.TotalUserTime.QuadPart); emit("memory_query_ok", memory != FALSE);
    emit("peak_memory_bytes", limits.PeakProcessMemoryUsed); emit("child_resumed", 0);
    bool ok = finished && !deadline && state->passed && killed && waited == WAIT_OBJECT_0 && latency <= TerminationMs &&
        exitOK && code == 123 && accounting && !account.ActiveProcesses && memory;
    emit("inspection_passed", ok);
    // Release completed inspection references before the unchanged profile cleanup.
    // A timed-out inspector retains only its private state until helper exit.
    if (finished) state.reset();
    if (!ok) throw std::string("a3 inspection refused");
    throw FeasibilityComplete{};
}
} // namespace a3
