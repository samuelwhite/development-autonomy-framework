// A8 GENERATED-BUILD ONLY. No native execution is authorised by this source.
#pragma once
#include "identity.h"
#include <array>
#include <atomic>
#include <thread>
#include <exception>
#include <iostream>
namespace a3 { struct State; struct Inventory; }
namespace a8 {
inline constexpr DWORD FailedWait = WAIT_FAILED;
inline unsigned sequence = 0;
inline bool select(const wchar_t* name) {
    if (std::wstring(name) == L"A8-C0") sequence = 1;
    else if (std::wstring(name) == L"A8-S1") sequence = 2;
    else return false;
    return true;
}
inline unsigned long long clock() noexcept {
    LARGE_INTEGER value{};
    return QueryPerformanceCounter(&value) && value.QuadPart > 0 ? value.QuadPart : 0;
}
struct Row { const char* key = nullptr; unsigned long long value = 0; };
template<unsigned N> struct Rows {
    std::array<Row, N> rows{};
    std::atomic<unsigned> count{0};
    std::atomic<bool> overflow{false};
    void put(const char* key, unsigned long long value) noexcept {
        unsigned at = count.load(std::memory_order_relaxed);
        if (at == N) { overflow.store(true); return; }
        rows[at] = {key, value};
        count.store(at + 1, std::memory_order_release);
    }
};
struct Context {
    // Separate single-writer buffers. Keys are static literals, never allocations.
    Rows<44> supervisor;
    Rows<10> inspector;
    Rows<6> observer;
    HANDLE gate = nullptr, entered = nullptr, observerThread = nullptr;
    ULONGLONG observerStart = 0, inspectionStart = 0;
    unsigned inspectorCut = 0, observerCut = 0;
    unsigned sharedEmit = 0;
    bool safetyReturned = false;
    ~Context() {
        if (observerThread) CloseHandle(observerThread);
        if (entered) CloseHandle(entered);
        if (gate) CloseHandle(gate);
    }
};
inline std::shared_ptr<Context> context;
inline void emit(const char* key, unsigned long long value) {
    std::cerr << "{\"native\":\"a8_" << key << "\",\"value\":" << value << "}\n";
}
inline void started(ULONGLONG start) noexcept {
    context->inspectionStart = start;
    context->supervisor.put("supervisor_tid", GetCurrentThreadId());
    context->supervisor.put("start_tick", start);
    context->supervisor.put("start_qpc", clock());
}
void boundary(a3::State&, const a3::Inventory&, const std::shared_ptr<Context>&);
void decision(a3::State&, DWORD, unsigned long long, bool) noexcept;
inline void killing() noexcept { context->supervisor.put("kill_qpc", clock()); }
inline void terminated() noexcept {
    context->safetyReturned = true; context->supervisor.put("terminated_qpc", clock());
}
inline void published(unsigned count) noexcept {
    context->sharedEmit = count; context->supervisor.put("shared_emit", count);
}
}
#include "a8-suspended-inspection.generated.h"
namespace a8 {
inline DWORD remaining(ULONGLONG began) noexcept {
    ULONGLONG elapsed = GetTickCount64() - began;
    return elapsed >= a3::DeadlineMs ? 0 : DWORD(a3::DeadlineMs - elapsed);
}
inline void observe(std::shared_ptr<Context> c) noexcept {
    c->observer.put("observer_tid", GetCurrentThreadId());
    DWORD wait = WaitForSingleObject(c->entered, remaining(c->observerStart));
    DWORD error = wait == WAIT_FAILED ? GetLastError() : 0;
    c->observer.put("entered_wait", wait);
    c->observer.put("entered_error", error);
    // Only exact owned valid handles. This zero-time read never releases the gate.
    c->observer.put("gate_wait", wait == WAIT_OBJECT_0 ? WaitForSingleObject(c->gate, 0) : WAIT_FAILED);
    c->observer.put("observed_qpc", clock());
}
inline void boundary(a3::State& s, const a3::Inventory& first, const std::shared_ptr<Context>& c) {
    bool ready = first.values.size() == 3 && first.pipes.size() == 3 && first.hostile.size() == 3;
    unsigned seen = 0;
    for (unsigned i = 0; ready && i < 3; ++i) {
        DWORD mask = first.pipes[i];
        ready = (mask == 1 || mask == 2 || mask == 4) && !(seen & mask) && !first.hostile[i];
        unsigned stream = mask == 1 ? 0 : mask == 2 ? 1 : 2;
        ready = ready && first.values[i] == s.pipeValues[stream]; seen |= mask;
    }
    c->inspector.put("inspector_tid", GetCurrentThreadId());
    c->inspector.put("boundary_ready", ready && seen == 7 && !s.stop.load());
    if (!ready || seen != 7 || s.stop.load()) throw a3::Failed{};
    c->inspector.put("call_qpc", clock());
    // The sole entered-event signal. No gate modification handle exists.
    DWORD result = SignalObjectAndWait(c->entered, c->gate, INFINITE, FALSE);
    DWORD error = result == WAIT_FAILED ? GetLastError() : 0;
    c->inspector.put("call_return", result); c->inspector.put("call_error", error);
    c->inspector.put("return_qpc", clock());
    if (result != WAIT_OBJECT_0) throw a3::Failed{};
    DWORD acknowledged = WaitForSingleObject(c->observerThread, remaining(c->inspectionStart));
    c->inspector.put("ack_wait", acknowledged); c->inspector.put("ack_qpc", clock());
    if (acknowledged != WAIT_OBJECT_0) throw a3::Failed{};
}
inline void decision(a3::State& s, DWORD error, unsigned long long waited, bool deadline) noexcept {
    auto& c = *context;
    c.inspectorCut = c.inspector.count.load(std::memory_order_acquire);
    c.observerCut = c.observer.count.load(std::memory_order_acquire);
    c.supervisor.put("wait_error", error); c.supervisor.put("wait_qpc", waited);
    c.supervisor.put("raw_deadline", deadline);
    c.supervisor.put("done", s.done.load(std::memory_order_acquire));
    c.supervisor.put("stop", s.stop.load());
    c.supervisor.put("inspector_cut", c.inspectorCut); c.supervisor.put("observer_cut", c.observerCut);
    c.supervisor.put("shared_cut", s.published.load(std::memory_order_acquire));
}
inline void witness(Context& c, HANDLE process, HANDLE thread, HANDLE job) noexcept {
    c.supervisor.put("witness_wait", WaitForSingleObject(process, 0));
    DWORD code = 0; BOOL ok = GetExitCodeProcess(process, &code);
    c.supervisor.put("witness_exit_ok", ok != FALSE); c.supervisor.put("witness_exit", code);
    c.supervisor.put("witness_pid", GetProcessId(process));
    FILETIME created{}, exited{}, kernel{}, user{};
    ok = GetProcessTimes(process, &created, &exited, &kernel, &user);
    c.supervisor.put("witness_times_ok", ok != FALSE);
    c.supervisor.put("witness_creation", a3::timeValue(created));
    c.supervisor.put("witness_tid", GetThreadId(thread));
    ok = GetExitCodeThread(thread, &code);
    c.supervisor.put("witness_thread_ok", ok != FALSE); c.supervisor.put("witness_thread_exit", code);
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION account{};
    ok = QueryInformationJobObject(job, JobObjectBasicAccountingInformation, &account, sizeof(account), nullptr);
    c.supervisor.put("witness_job_ok", ok != FALSE); c.supervisor.put("witness_active", account.ActiveProcesses);
    c.supervisor.put("witness_qpc", clock());
}
template<unsigned N> inline void emitRows(const Rows<N>& rows, unsigned count) {
    for (unsigned i = 0; i < count; ++i) emit(rows.rows[i].key, rows.rows[i].value);
}
[[noreturn]] inline void beforeResume(HANDLE process, HANDLE thread, HANDLE job) {
    auto c = std::make_shared<Context>(); context = c;
    std::thread observer;
    std::exception_ptr failure;
    try {
        c->gate = CreateEventExW(nullptr, nullptr, CREATE_EVENT_MANUAL_RESET |
            (sequence == 1 ? CREATE_EVENT_INITIAL_SET : 0), SYNCHRONIZE);
        c->entered = CreateEventExW(nullptr, nullptr, CREATE_EVENT_MANUAL_RESET,
            SYNCHRONIZE | EVENT_MODIFY_STATE);
        if (!c->gate || !c->entered) throw std::string("a8 owned event creation");
        DWORD gateFlags = 0, enteredFlags = 0;
        if (!GetHandleInformation(c->gate, &gateFlags) || !GetHandleInformation(c->entered, &enteredFlags))
            throw std::string("a8 owned event flags");
        LARGE_INTEGER frequency{};
        if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0) throw std::string("a8 clock");
        c->supervisor.put("case", sequence - 1); c->supervisor.put("sequence", sequence);
        c->supervisor.put("gate_initial", sequence == 1); c->supervisor.put("gate_flags", gateFlags);
        c->supervisor.put("entered_flags", enteredFlags); c->supervisor.put("qpc_frequency", frequency.QuadPart);
        c->observerStart = GetTickCount64(); c->supervisor.put("observer_start_tick", c->observerStart);
        observer = std::thread(observe, c);
        if (!DuplicateHandle(GetCurrentProcess(), observer.native_handle(), GetCurrentProcess(),
            &c->observerThread, SYNCHRONIZE, FALSE, 0)) throw std::string("a8 observer retention");
        a3::beforeResume(process, thread, job); // Original supervisor, original exception/result.
    } catch (...) { failure = std::current_exception(); }
    // No evidence I/O until original safety actions have run (or failed).
    if (c->safetyReturned) witness(*c, process, thread, job);
    DWORD observerWait = observer.joinable() ? WaitForSingleObject(observer.native_handle(), 0) : WAIT_FAILED;
    c->supervisor.put("observer_thread_wait", observerWait);
    if (observer.joinable()) {
        if (observerWait == WAIT_OBJECT_0) observer.join(); else observer.detach();
    }
    // Detect publication after the original frozen prefix without reading live
    // non-atomic inspection flags. Later rows never repair the original result.
    c->supervisor.put("inspector_final", c->inspector.count.load(std::memory_order_acquire));
    c->supervisor.put("observer_final", c->observer.count.load(std::memory_order_acquire));
    unsigned count = c->supervisor.count.load(std::memory_order_acquire);
    bool bounded = count + c->inspectorCut + c->observerCut + 2 <= 64 &&
        count + c->inspectorCut + c->observerCut + c->sharedEmit <= 384 &&
        !c->supervisor.overflow.load() && !c->inspector.overflow.load() && !c->observer.overflow.load();
    // Freeze both private prefixes at the original decision, never read live flags.
    if (c->safetyReturned) {
        emit("rows_bounded", bounded); emit("private_rows", count + c->inspectorCut + c->observerCut);
        if (bounded) {
            emitRows(c->supervisor, count); emitRows(c->inspector, c->inspectorCut); emitRows(c->observer, c->observerCut);
        }
    }
    context.reset();
    if (failure) std::rethrow_exception(failure);
    throw std::string("a8 unexpected supervisor return");
}
} // namespace a8
