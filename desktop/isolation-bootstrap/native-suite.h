// Fixed adversarial fixture probes. No supplied task, script or command is run.
#include <stdio.h>
#include <wchar.h>
#include <winternl.h>
#include <wincrypt.h>
#include <wincred.h>
#include <aclapi.h>
#include <winsock2.h>
#include <ws2tcpip.h>
static wchar_t suiteRoot[1024], suiteProfile[1024], suiteName[256];
static HMODULE advapi, userenvModule, cryptModule, socketModule;
static DWORD failureCount;
static void result(const char* name, const char* status, DWORD code) {
    printf("{\"probe\":\"%s\",\"status\":\"%s\",\"code\":%lu}\n", name, status, code);
    fflush(stdout);
}
static void expect(const char* name, DWORD code, BOOL allowed) {
    result(name, code == 0 ? "allowed" : code == 5 || code == 367 || code == 10013 ? "denied" : "error", code);
    if ((code == 0) != allowed) ++failureCount;
}
static FARPROC api(HMODULE module, const char* function, const char* probe) {
    FARPROC p = module ? GetProcAddress(module, function) : 0;
    if (!p) { result(probe, "unavailable", module ? GetLastError() : 0); ++failureCount; }
    return p;
}
static HMODULE systemModule(const wchar_t* name, const char* label) {
    HMODULE m=LoadLibraryExW(name,0,LOAD_LIBRARY_SEARCH_SYSTEM32);
    result(label,m?"allowed":"unavailable",m?0:GetLastError()); return m;
}
static void path(wchar_t* out, const wchar_t* base, const wchar_t* leaf) {
    swprintf_s(out, 1200, L"%s\\%s", base, leaf);
}
static DWORD openFixture(const wchar_t* file, BOOL writing, BOOL creating) {
    HANDLE h = CreateFileW(file, writing ? (creating ? FILE_WRITE_DATA : FILE_APPEND_DATA) : FILE_READ_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, 0,
        creating ? CREATE_NEW : OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return GetLastError();
    DWORD n = 0, code = 0; char data[64];
    if (!(writing ? WriteFile(h, "SYNTHETIC", 9, &n, 0) : ReadFile(h, data, sizeof(data), &n, 0))) code = GetLastError();
    CloseHandle(h); if (creating) DeleteFileW(file); return code;
}
static void fixture(const char* name, const wchar_t* base, const wchar_t* leaf, BOOL writing, BOOL creating, BOOL allowed) {
    wchar_t file[1200]; path(file, base, leaf); expect(name, openFixture(file, writing, creating), allowed);
}
static void dacl(const char* label, const wchar_t* file) {
    typedef DWORD (WINAPI* F)(LPWSTR, SE_OBJECT_TYPE, SECURITY_INFORMATION, PSID, PSID, PACL, PACL);
    F f = (F)api(advapi, "SetNamedSecurityInfoW", label);
    if (f) expect(label, f((LPWSTR)file, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, 0, 0, 0, 0), FALSE);
}
static void registryProfile(const char* label, REGSAM access) {
    typedef HRESULT (WINAPI* F)(REGSAM, HKEY*);
    F f = (F)api(userenvModule, "GetAppContainerRegistryLocation", label);
    if (!f) return;
    HKEY key = 0; HRESULT hr = f(access, &key);
    typedef LSTATUS (WINAPI* Close)(HKEY);
    Close close = (Close)api(advapi, "RegCloseKey", "registry_close");
    if (key && close) close(key);
    expect(label, FAILED(hr) ? HRESULT_CODE(hr) : 0, FALSE);
}
static void registryTests(void) {
    typedef LSTATUS (WINAPI* Open)(HKEY,LPCWSTR,DWORD,REGSAM,PHKEY);
    typedef LSTATUS (WINAPI* Query)(HKEY,LPCWSTR,LPDWORD,LPDWORD,LPBYTE,LPDWORD);
    typedef LSTATUS (WINAPI* Close)(HKEY);
    typedef LSTATUS (WINAPI* Create)(HKEY,LPCWSTR,DWORD,LPWSTR,DWORD,REGSAM,const LPSECURITY_ATTRIBUTES,PHKEY,LPDWORD);
    typedef LSTATUS (WINAPI* Delete)(HKEY,LPCWSTR);
    Open open=(Open)api(advapi,"RegOpenKeyExW","registry_open");
    Query query=(Query)api(advapi,"RegQueryValueExW","registry_query");
    Close close=(Close)api(advapi,"RegCloseKey","registry_close");
    Create create=(Create)api(advapi,"RegCreateKeyExW","registry_create");
    Delete remove=(Delete)api(advapi,"RegDeleteKeyW","registry_delete");
    if (!open || !query || !close || !create || !remove) return;
    HKEY key=0; DWORD code=open(HKEY_LOCAL_MACHINE,L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",0,KEY_READ,&key);
    BYTE data[128]; DWORD size=sizeof(data);
    if (!code) { code=query(key,L"CurrentBuildNumber",0,0,data,&size); close(key); }
    expect("registry_machine_read",code,TRUE);
    wchar_t name[512]; swprintf_s(name,512,L"Software\\%s",suiteName);
    code=open(HKEY_CURRENT_USER,name,0,KEY_READ,&key);
    if (!code) { size=sizeof(data); code=query(key,L"HostPrivateSentinel",0,0,data,&size); close(key); }
    expect("read_host_private_registry_fixture",code,FALSE);
    code=create(HKEY_CURRENT_USER,name,0,0,0,KEY_WRITE,0,&key,0);
    if (!code) { close(key); remove(HKEY_CURRENT_USER,name); }
    expect("registry_user_write",code,FALSE);
    registryProfile("registry_profile_write",KEY_READ|KEY_WRITE);
    registryProfile("registry_profile_write_dacl",WRITE_DAC);
}
static void profileReinitialize(void) {
    typedef HRESULT (WINAPI* F)(PCWSTR,PCWSTR,PCWSTR,PSID_AND_ATTRIBUTES,DWORD,PSID*);
    F f=(F)api(userenvModule,"CreateAppContainerProfile","reinitialize_own_profile");
    if (!f) return;
    PSID sid=0; HRESULT hr=f(suiteName,L"DAF diagnostic",L"synthetic",0,0,&sid);
    typedef PVOID (WINAPI* Free)(PSID); Free freeSid=(Free)GetProcAddress(advapi,"FreeSid");
    if (sid && freeSid) freeSid(sid);
    expect("reinitialize_own_profile",FAILED(hr)?HRESULT_CODE(hr):0,FALSE);
}
static void credentials(void) {
    typedef BOOL (WINAPI* Read)(LPCWSTR,DWORD,DWORD,PCREDENTIALW*);
    typedef VOID (WINAPI* Free)(PVOID);
    Read read=(Read)api(advapi,"CredReadW","host_credential_read");
    Free freeCredential=(Free)GetProcAddress(advapi,"CredFree");
    if (read) {
        PCREDENTIALW value=0; BOOL ok=read(suiteName,CRED_TYPE_GENERIC,0,&value);
        DWORD code=ok?0:GetLastError(); if (value && freeCredential) freeCredential(value);
        expect("host_credential_read",code,FALSE);
    }
    typedef BOOL (WINAPI* Decrypt)(DATA_BLOB*,LPWSTR*,DATA_BLOB*,PVOID,CRYPTPROTECT_PROMPTSTRUCT*,DWORD,DATA_BLOB*);
    Decrypt decrypt=(Decrypt)api(cryptModule,"CryptUnprotectData","host_dpapi_decrypt");
    if (decrypt) {
        wchar_t file[1200]; path(file,suiteRoot,L"protected.bin");
        HANDLE h=CreateFileW(file,GENERIC_READ,FILE_SHARE_READ,0,OPEN_EXISTING,0,0);
        BYTE data[4096]; DWORD n=0;
        if (h==INVALID_HANDLE_VALUE || !ReadFile(h,data,sizeof(data),&n,0)) { result("dpapi_fixture","error",GetLastError()); ++failureCount; }
        else {
            DATA_BLOB input={n,data}, output={0,0}; BOOL ok=decrypt(&input,0,0,0,0,CRYPTPROTECT_UI_FORBIDDEN,&output);
            DWORD code=ok?0:GetLastError(); if (output.pbData) LocalFree(output.pbData);
            expect("host_dpapi_decrypt",code,FALSE);
        }
        if (h!=INVALID_HANDLE_VALUE) CloseHandle(h);
    }
}
static void network(void) {
    typedef int (WSAAPI* Startup)(WORD,LPWSADATA); typedef SOCKET (WSAAPI* Socket)(int,int,int);
    typedef int (WSAAPI* Connect)(SOCKET,const struct sockaddr*,int);
    typedef int (WSAAPI* Send)(SOCKET,const char*,int,int,const struct sockaddr*,int);
    typedef int (WSAAPI* Ioctl)(SOCKET,long,u_long*); typedef int (WSAAPI* Close)(SOCKET);
    typedef int (WSAAPI* Error)(void); typedef int (WSAAPI* Cleanup)(void);
    typedef INT (WSAAPI* Resolve)(PCWSTR,PCWSTR,const ADDRINFOW*,PADDRINFOW*);
    typedef VOID (WSAAPI* Free)(PADDRINFOW);
    Startup startup=(Startup)api(socketModule,"WSAStartup","socket_startup");
    Socket socketFn=(Socket)api(socketModule,"socket","socket_create");
    Connect connectFn=(Connect)api(socketModule,"connect","socket_connect");
    Send sendFn=(Send)api(socketModule,"sendto","socket_sendto");
    Ioctl ioctlFn=(Ioctl)api(socketModule,"ioctlsocket","socket_ioctl");
    Close closeFn=(Close)api(socketModule,"closesocket","socket_close");
    Error errorFn=(Error)api(socketModule,"WSAGetLastError","socket_error");
    Cleanup cleanupFn=(Cleanup)api(socketModule,"WSACleanup","socket_cleanup");
    if (!startup||!socketFn||!connectFn||!sendFn||!ioctlFn||!closeFn||!errorFn||!cleanupFn) return;
    WSADATA data; int code=startup(MAKEWORD(2,2),&data);
    if (code) { result("socket_startup","error",code); ++failureCount; return; }
    const char* names[]={"loopback_tcp","loopback_udp","external_tcp_testnet","external_udp_testnet"};
    for (int i=0;i<4;++i) {
        SOCKET s=socketFn(AF_INET,i%2?SOCK_DGRAM:SOCK_STREAM,0);
        code=s==INVALID_SOCKET?errorFn():0;
        if (s!=INVALID_SOCKET) {
            u_long nonblocking=1; ioctlFn(s,FIONBIO,&nonblocking);
            struct sockaddr_in address={0}; address.sin_family=AF_INET; address.sin_port=(u_short)((49372>>8)|((49372&255)<<8));
            unsigned char* bytes=(unsigned char*)&address.sin_addr;
            bytes[0]=i<2?127:203; bytes[1]=0; bytes[2]=i<2?0:113; bytes[3]=1;
            int r=i%2?sendFn(s,"DAF synthetic isolation probe",29,0,(struct sockaddr*)&address,sizeof(address)):
                connectFn(s,(struct sockaddr*)&address,sizeof(address));
            code=r==SOCKET_ERROR?errorFn():0; closeFn(s);
        }
        expect(names[i],code,FALSE);
        if (code!=WSAEACCES) ++failureCount; // timeout/refusal is not network isolation.
    }
    Resolve resolve=(Resolve)api(socketModule,"GetAddrInfoW","dns_resolution");
    Free freeInfo=(Free)GetProcAddress(socketModule,"FreeAddrInfoW");
    if (resolve) { ADDRINFOW* info=0; code=resolve(L"example.com",L"443",0,&info); if(info&&freeInfo) freeInfo(info); expect("dns_resolution",code,FALSE); }
    cleanupFn();
}
static void childProbe(BOOL breakaway) {
    wchar_t exe[1200]; path(exe,suiteRoot,L"native-minimal.exe");
    STARTUPINFOW start={0}; start.cb=sizeof(start); PROCESS_INFORMATION pi={0};
    BOOL ok=CreateProcessW(exe,0,0,0,FALSE,CREATE_NO_WINDOW|(breakaway?CREATE_BREAKAWAY_FROM_JOB:0),0,0,&start,&pi);
    DWORD code=ok?0:GetLastError();
    if (ok) { TerminateProcess(pi.hProcess,127); WaitForSingleObject(pi.hProcess,3000); CloseHandle(pi.hThread); CloseHandle(pi.hProcess); }
    expect(breakaway?"breakaway_child":"child_process",code,FALSE);
}
static void cngDependency(void) {
    typedef NTSTATUS (NTAPI* Open)(PHANDLE,ACCESS_MASK,POBJECT_ATTRIBUTES,PIO_STATUS_BLOCK,ULONG,ULONG);
    Open open=(Open)GetProcAddress(GetModuleHandleW(L"ntdll.dll"),"NtOpenFile");
    wchar_t value[]=L"\\Device\\KsecDD";
    UNICODE_STRING name={(USHORT)(sizeof(value)-2),(USHORT)sizeof(value),value};
    OBJECT_ATTRIBUTES attrs={sizeof(attrs),0,&name,OBJ_CASE_INSENSITIVE,0,0};
    for(int i=0;i<2;++i) {
        HANDLE h=0; IO_STATUS_BLOCK io={0};
        NTSTATUS status=open(&h,SYNCHRONIZE|FILE_READ_DATA|(i?FILE_WRITE_DATA:0),&attrs,&io,
            FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,FILE_SYNCHRONOUS_IO_NONALERT);
        result(i?"ksecdd_read_write_open":"ksecdd_read_open",status>=0?"allowed":"error",(DWORD)status);
        if(h) CloseHandle(h); // No read/write/ioctl is issued to the device.
    }
    HMODULE bcrypt=LoadLibraryExW(L"bcrypt.dll",0,LOAD_LIBRARY_SEARCH_SYSTEM32);
    result("bcrypt_dynamic_load",bcrypt?"allowed":"error",bcrypt?0:GetLastError());
    if(bcrypt) FreeLibrary(bcrypt);
}
static int fullSuite(void) {
    wchar_t mode[64]; GetEnvironmentVariableW(L"DAF_PROBE_MODE",mode,64);
    if (!wcscmp(mode,L"hold")) { result("hold_ready","observed",0); Sleep(60000); return 0; }
    if (!wcscmp(mode,L"cpu")) { result("cpu_ready","observed",0); volatile unsigned long n=0; for(;;) ++n; }
    if (!wcscmp(mode,L"memory")) {
        void* control=VirtualAlloc(0,32*1024*1024,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
        result("memory_positive_control",control?"allowed":"error",control?0:GetLastError());
        if(!control) return 1;
        VirtualFree(control,0,MEM_RELEASE);
        void* memory=VirtualAlloc(0,160*1024*1024,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
        DWORD code=memory?0:GetLastError(); result("memory_limit",memory?"allowed":"denied",code);
        if(memory) VirtualFree(memory,0,MEM_RELEASE); return memory?1:0;
    }
    GetEnvironmentVariableW(L"DAF_ROOT",suiteRoot,1024);
    GetEnvironmentVariableW(L"DAF_PROFILE",suiteProfile,1024);
    GetEnvironmentVariableW(L"DAF_CREDENTIAL_TARGET",suiteName,256);
    if (!wcscmp(mode,L"dependency")) { cngDependency(); return 0; }
    advapi=systemModule(L"advapi32.dll","load_advapi32");
    userenvModule=systemModule(L"userenv.dll","load_userenv");
    cryptModule=systemModule(L"crypt32.dll","load_crypt32");
    socketModule=systemModule(L"ws2_32.dll","load_ws2_32");
    fixture("read_allowed_fixture",suiteRoot,L"allowed.txt",FALSE,FALSE,TRUE);
    fixture("read_host_private_fixture",suiteRoot,L"private.txt",FALSE,FALSE,FALSE);
    fixture("write_workspace",suiteRoot,L"worker-created.txt",TRUE,TRUE,FALSE);
    wchar_t runtime[1200]; path(runtime,suiteRoot,L"runtime");
    fixture("write_runtime",runtime,L"worker-created.txt",TRUE,TRUE,FALSE);
    fixture("write_profile_root",suiteProfile,L"worker-created.txt",TRUE,TRUE,FALSE);
    wchar_t parent[1200]; wcscpy_s(parent,1200,suiteProfile); *wcsrchr(parent,L'\\')=0;
    fixture("write_profile_package_root",parent,L"worker-created.txt",TRUE,TRUE,FALSE);
    wchar_t temp[1200]; path(temp,suiteProfile,L"Temp");
    fixture("write_profile_temp",temp,L"worker-created.txt",TRUE,TRUE,FALSE);
    wchar_t effective[1200]; GetEnvironmentVariableW(L"TEMP",effective,1200);
    fixture("write_effective_temp",effective,L"worker-created.txt",TRUE,TRUE,FALSE);
    fixture("read_profile_sentinel",suiteProfile,L"owned-sentinel.txt",FALSE,FALSE,TRUE);
    fixture("append_profile_file",suiteProfile,L"owned-sentinel.txt",TRUE,FALSE,FALSE);
    wchar_t sentinel[1200]; path(sentinel,suiteProfile,L"owned-sentinel.txt");
    dacl("replace_profile_dacl",sentinel);
    fixture("append_after_dacl_attempt",suiteProfile,L"owned-sentinel.txt",TRUE,FALSE,FALSE);
    dacl("replace_profile_root_dacl",suiteProfile); dacl("replace_temp_dacl",temp);
    fixture("write_after_directory_dacl_attempt",suiteProfile,L"worker-created.txt",TRUE,TRUE,FALSE);
    wchar_t user[1200], windows[1200]; GetEnvironmentVariableW(L"USERPROFILE",user,1200);
    GetEnvironmentVariableW(L"SystemRoot",windows,1200); wcscat_s(windows,1200,L"\\Temp");
    fixture("write_host_profile",user,suiteName,TRUE,TRUE,FALSE);
    fixture("write_windows_temp",windows,suiteName,TRUE,TRUE,FALSE);
    registryTests(); profileReinitialize();
    fixture("write_profile_after_reinitialize",suiteProfile,L"worker-created.txt",TRUE,TRUE,FALSE);
    fixture("write_temp_after_reinitialize",temp,L"worker-created.txt",TRUE,TRUE,FALSE);
    registryProfile("registry_write_after_reinitialize",KEY_READ|KEY_WRITE);
    credentials(); network(); childProbe(FALSE); childProbe(TRUE);
    result("native_suite_complete","observed",failureCount); return failureCount?1:0;
}
