// Closed little-endian v1 byte protocol. Fixed packaged Windows x64 entry points.
#pragma once
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "sha256.h"
#include "bindings.h"
enum Failure { OK=0, FRAME=1, LIMIT=2, TEXT=3, BINDING=4, OCCURRENCE=5, PREIMAGE=6, CANDIDATE=7, IO=8 };
#pragma pack(push,1)
struct Request {
    char magic[8]; uint32_t version, role, sourceSize, oldSize, newSize, candidateSize;
    unsigned char manifest[32], planCommit[20], sourceBlob[20], planDigest[32];
    unsigned char sourceDigest[32], oldDigest[32], newDigest[32], expectedDigest[32];
    unsigned char policyDigest[32], buildDigest[32];
};
struct Response {
    char magic[8]; uint32_t version, role, status, size;
    unsigned char manifest[32], digest[32];
};
#pragma pack(pop)
static_assert(sizeof(Request)==328, "wire layout");
static_assert(sizeof(Response)==88, "wire layout");
static unsigned char sourceBytes[65536], oldBytes[8192], newBytes[8192], candidateBytes[65536];
static bool readExact(void* data, DWORD size) {
    DWORD at=0, n=0;
    while(at<size) {
        if(!ReadFile(GetStdHandle(STD_INPUT_HANDLE),(unsigned char*)data+at,size-at,&n,nullptr)||!n) return false;
        at+=n;
    }
    return true;
}
static bool endOfInput() {
    unsigned char extra; DWORD n=0;
    BOOL ok=ReadFile(GetStdHandle(STD_INPUT_HANDLE),&extra,1,&n,nullptr);
    return (ok && n==0)||(!ok && GetLastError()==ERROR_BROKEN_PIPE);
}
static bool writeExact(const void* data, DWORD size) {
    DWORD at=0,n=0;
    while(at<size) {
        if(!WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),(const unsigned char*)data+at,size-at,&n,nullptr)||!n) return false;
        at+=n;
    }
    return true;
}
static bool utf8(const unsigned char* p, size_t n) {
    for(size_t i=0;i<n;) {
        unsigned c=p[i++]; if(c==0) return false;
        if(c<0x80) continue;
        unsigned need, value, minimum;
        if(c>=0xc2&&c<=0xdf) {need=1;value=c&31;minimum=0x80;}
        else if(c>=0xe0&&c<=0xef) {need=2;value=c&15;minimum=0x800;}
        else if(c>=0xf0&&c<=0xf4) {need=3;value=c&7;minimum=0x10000;}
        else return false;
        if(n-i<need) return false;
        while(need--) {c=p[i++];if((c&0xc0)!=0x80) return false;value=(value<<6)|(c&63);}
        if(value<minimum||value>0x10ffff||(value>=0xd800&&value<=0xdfff)) return false;
    }
    return true;
}
static bool hashMatches(const unsigned char* p, size_t n, const unsigned char* expected) {
    unsigned char hash[32]; sha256(p,n,hash); return memcmp(hash,expected,32)==0;
}
static bool nonzero(const unsigned char* p, size_t n) {unsigned v=0;for(size_t i=0;i<n;++i)v|=p[i];return v!=0;}
static Failure receive(Request& r, unsigned role) {
    if(!readExact(&r,sizeof(r))) return FRAME;
    if(memcmp(r.magic,"DAFN21A1",8)||r.version!=1||r.role!=role) return FRAME;
    if(!r.sourceSize||r.sourceSize>65536||!r.oldSize||r.oldSize>8192||!r.newSize||r.newSize>8192||r.candidateSize>65536) return LIMIT;
    if((role==1&&r.candidateSize)||(role==2&&!r.candidateSize)) return FRAME;
    if(!readExact(sourceBytes,r.sourceSize)||!readExact(oldBytes,r.oldSize)||!readExact(newBytes,r.newSize)||
       !readExact(candidateBytes,r.candidateSize)||!endOfInput()) return FRAME;
    if(!utf8(sourceBytes,r.sourceSize)||!utf8(oldBytes,r.oldSize)||!utf8(newBytes,r.newSize)||
       (r.candidateSize&&!utf8(candidateBytes,r.candidateSize))) return TEXT;
    if(!nonzero(r.manifest,32)||!nonzero(r.buildDigest,32)||memcmp(r.planCommit,PLAN_COMMIT,20)||
       memcmp(r.sourceBlob,SOURCE_BLOB,20)||memcmp(r.planDigest,PLAN_DIGEST,32)||memcmp(r.policyDigest,POLICY_DIGEST,32)||
       memcmp(r.sourceDigest,SOURCE_DIGEST,32)||memcmp(r.oldDigest,OLD_DIGEST,32)||memcmp(r.newDigest,NEW_DIGEST,32)||
       memcmp(r.expectedDigest,EXPECTED_DIGEST,32)) return BINDING;
    return OK;
}
static Failure validateBytes(const Request& r) {
    if(!hashMatches(sourceBytes,r.sourceSize,r.sourceDigest)||!hashMatches(oldBytes,r.oldSize,r.oldDigest)||
       !hashMatches(newBytes,r.newSize,r.newDigest)) return PREIMAGE;
    if(r.oldSize==r.newSize&&!memcmp(oldBytes,newBytes,r.oldSize)) return BINDING;
    return OK;
}
static int respond(const Request& r, unsigned role, Failure status, unsigned size=0) {
    Response out{};memcpy(out.magic,"DAFO21A1",8);out.version=1;out.role=role;out.status=status;
    if(status==OK) {out.size=size;memcpy(out.manifest,r.manifest,32);sha256(candidateBytes,size,out.digest);}
    // A failure discloses no input bytes or identifiers, even after partial input.
    if(!writeExact(&out,sizeof(out))) return IO;
    if(status==OK&&role==1&&!writeExact(candidateBytes,size)) return IO;
    return (int)status;
}
