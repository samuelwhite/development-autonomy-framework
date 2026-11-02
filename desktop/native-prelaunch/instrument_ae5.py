"""Pinned diagnostic copies only. Exact inverse of EVERY generated source file."""

import hashlib
import sys
from pathlib import Path

from instrument_a8 import canonical
from instrument_harness import ACCEPTED

SOURCE = Path(__file__).resolve().parent
LAUNCHER_SHA = "eb996807e806917660c1278fed391d067005d81e7a647b36ca51eb6d95fff1f4"


def changes():
    # Unique anchors; no changes to security arguments, limits, predicate or snapshots.
    return (
        (
            b"static void grant(const fs::path& p, PSID sid, DWORD access, bool inherit) {\n",
            b"static void grant(const fs::path& p, PSID sid, DWORD access, bool inherit) {\n"
            b"    HANDLE ae5Acl = ae5::aclBegin(p.wstring());\n",
        ),
        (
            b"    LocalFree(updated); LocalFree(sd);\n}",
            b"    ae5::aclEnd(ae5Acl);\n    LocalFree(updated); LocalFree(sd);\n}",
        ),
        (
            b"    code = RegCreateKeyExW(storage, sidString(appSid).c_str(),",
            b'    ae5::intent("registry", registryStorageParent + L"\\\\" + sidString(appSid));\n'
            b"    code = RegCreateKeyExW(storage, sidString(appSid).c_str(),",
        ),
        (
            b"    registryStorageCreated = disposition == REG_CREATED_NEW_KEY;",
            b"    registryStorageCreated = disposition == REG_CREATED_NEW_KEY;\n"
            b"    ae5::commit(true, registryStorageCreated);",
        ),
        (
            b"    PACL updated = readonlyAcl(KEY_READ, true);",
            b'    ae5::intent("acl", registryStorageParent + L"\\\\" + sidString(appSid),\n'
            b"        sealedRegistry, SE_REGISTRY_KEY, DACL_SECURITY_"
            b"INFORMATION, registryDescriptor);\n"
            b"    PACL updated = readonlyAcl(KEY_READ, true);",
        ),
        (
            b"    LocalFree(updated);\n}\nstatic void seal(",
            b"    ae5::commit(true);\n    LocalFree(updated);\n}\nstatic void seal(",
        ),
        (
            b"    sealed.push_back({h, sd, old});",
            b'    ae5::intent("acl", p.wstring(), h, SE_FILE_OBJECT, '
            b"DACL_SECURITY_INFORMATION, sd);\n"
            b"    sealed.push_back({h, sd, old});",
        ),
        (
            b"    LocalFree(updated);\n}\nstatic DWORD parentPid()",
            b"    ae5::commit(true);\n    LocalFree(updated);\n}\nstatic DWORD parentPid()",
        ),
        (
            b"        HRESULT hr = CreateAppContainerProfile(",
            b'        ae5::intent("profile", profileName);\n        HR'
            b"ESULT hr = CreateAppContainerProfile(",
        ),
        (
            b'        check(SUCCEEDED(hr), "create fresh AppContainer'
            b' profile"); created = true; appSid = sid;',
            b"        ae5::commit(SUCCEEDED(hr), SUCCEEDED(hr));\n"
            b'        check(SUCCEEDED(hr), "create fresh AppContainer'
            b' profile"); created = true; appSid = sid;',
        ),
        (
            b"        DWORD labelResult = SetNamedSecurityInfoW(",
            b'        HANDLE ae5Label = ae5::aclBegin((root / "ambien'
            b't-shared.txt").wstring(), LABEL_SECURITY_INFORMATION);\n'
            b"        DWORD labelResult = SetNamedSecurityInfoW(",
        ),
        (
            b"        labelResult = SetNamedSecurityInfoW(",
            b"        ae5::aclEnd(ae5Label);\n"
            b'        ae5Label = ae5::aclBegin((root / "dual-grant.tx'
            b't").wstring(), LABEL_SECURITY_INFORMATION);\n'
            b"        labelResult = SetNamedSecurityInfoW(",
        ),
        (
            b"        LocalFree(lowDescriptor);",
            b"        ae5::aclEnd(ae5Label);\n        LocalFree(lowDescriptor);",
        ),
        (
            b'        check(CredWriteW(&credential, 0), "write synthe'
            b'tic host credential"); credentialCreated = true;',
            b'        ae5::intent("credential", profileName);\n'
            b'        check(CredWriteW(&credential, 0), "write synthe'
            b'tic host credential"); credentialCreated = true;\n'
            b"        ae5::commit(true, true);",
        ),
        (
            b"        check(RegCreateKeyExW(HKEY_CURRENT_USER, fixtureName.c_str(),",
            b'        ae5::intent("registry", fixtureName);\n        c'
            b"heck(RegCreateKeyExW(HKEY_CURRENT_USER, fixtureName.c_s"
            b"tr(),",
        ),
        (
            b"        registryFixtureCreated = true;",
            b"        registryFixtureCreated = true;\n        ae5::commit(true, true);",
        ),
        (
            b'        check(parent != nullptr, "open supervising parent");',
            b'        check(parent != nullptr, "open supervising pare'
            b'nt");\n        ae5::verifyParent(parent);',
        ),
        (
            b"        privateDesktop = CreateDesktopW(",
            b'        ae5::intent("desktop", uniqueDesktop);\n        '
            b"privateDesktop = CreateDesktopW(",
        ),
        (
            b'        check(privateDesktop != nullptr, "create owned private desktop");',
            b'        check(privateDesktop != nullptr, "create owned '
            b'private desktop");\n        ae5::commit(true, true);',
        ),
        (
            b'        check(ResumeThread(thread) != (DWORD)-1, "resume");',
            b"        ae5::beforeResume(process, thread, job);\n"
            b'        check(ae5::neverResume(thread) != (DWORD)-1, "resume");',
        ),
        (
            b"    } catch (const std::string&)",
            b"    } catch (const a3::FeasibilityComplete&) { result ="
            b' 0; event("a3_controlled_stop", 1);\n'
            b"    } catch (const std::string&)",
        ),
        (
            b"    if (job) { TerminateJobObject(job, 126); CloseHandle(job); }",
            b"    ae5::cleanup(process);\n    if (job) { TerminateJobO"
            b"bject(job, 126); CloseHandle(job); }",
        ),
    )


def transform(raw, edits, expected):
    result = canonical(raw)
    if hashlib.sha256(result).hexdigest() != expected:
        raise ValueError("ae5_unreviewed_original")
    for before, after in edits:
        if result.count(before) != 1:
            raise ValueError(f"ae5_nonunique_anchor:{before[:80]!r}")
        result = result.replace(before, after)
    restored = inverse(result, edits)
    if restored != canonical(raw):
        raise ValueError("ae5_complete_inverse")
    return result


def inverse(raw, edits):
    result = canonical(raw)
    for before, after in reversed(edits):
        if result.count(after) != 1:
            raise ValueError("ae5_inverse_anchor")
        result = result.replace(after, before)
    return result


def launcher_changes():
    return (
        (b"// Separate A8-only fixture.", b"// Separate A-E5 compile-only fixture."),
        (b'#include "a8-stall-control.h"', b'#include "ae5-custody.h"'),
        (b'#include "a8-fixture-harness.h"', b'#include "ae5-fixture-harness.h"'),
        (
            b'    if (argc != 3 || std::wstring(argv[2]) != L"probe" '
            b"|| !a8::select(argv[1])) return 64;\n"
            b'    wchar_t mode[] = L"sealed"; wchar_t* arguments[]{argv[0], mode, argv[2]};\n'
            b"    int code = accepted_harness_main(3, arguments);",
            b"    if (argc != 1 || !ae5::nativeReleased()) return 64;\n"
            b"    int code = 1;\n"
            b"    try {\n"
            b"        ae5::initialize();\n"
            b'        wchar_t mode[] = L"sealed", probe[] = L"probe";\n'
            b"        wchar_t* arguments[]{argv[0], mode, probe};\n"
            b"        code = accepted_harness_main(3, arguments);\n"
            b"    } catch (...) { code = 1; }",
        ),
    )


def generate(output):
    frozen = output / "source"
    harness = (frozen / "native-foundation/harness.cpp").read_bytes()
    launcher = (frozen / "native-prelaunch/a8-fixture-host.cpp").read_bytes()
    products = {
        "ae5-fixture-harness.h": transform(harness, changes(), ACCEPTED),
        "ae5-fixture-host.cpp": transform(launcher, launcher_changes(), LAUNCHER_SHA),
        "ae5-baseline.cpp": b'#include "identity.h"\n#include "suspended-inspection.h"\n',
        "ae5-original-harness.h": canonical(harness),
    }
    products["ae5-host-baseline.cpp"] = products["ae5-fixture-host.cpp"].replace(
        b'"ae5-fixture-harness.h"', b'"ae5-original-harness.h"'
    )
    snippets = b'#include "ae5-custody.h"\n'
    for index, (before, after) in enumerate(changes()):
        for kind, raw in (("before", before), ("after", after)):
            snippets += f'\n#line 1 "ae5-{kind}-{index:02d}"\n'.encode() + raw + b"\n"
    products["ae5-transform-tokens.cpp"] = snippets
    for name, raw in products.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)


if __name__ == "__main__":
    generate(Path(sys.argv[1]).resolve())
