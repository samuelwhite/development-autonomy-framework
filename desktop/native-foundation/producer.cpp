#include "wire.h"
// One literal, byte-oriented transformation. No paths, diagnostics or dynamic loading.
int main() {
    Request r{}; Failure status=receive(r,1);size_t found=0,count=0;
    if(status==OK) {
        if(r.oldSize<=r.sourceSize) for(size_t i=0;i<=r.sourceSize-r.oldSize;++i)
            if(!memcmp(sourceBytes+i,oldBytes,r.oldSize)) {found=i;++count;}
        if(count!=1) status=OCCURRENCE;
        else status=validateBytes(r);
    }
    unsigned size=0;
    if(status==OK) {
        size=r.sourceSize-r.oldSize+r.newSize;
        if(size>65536) status=LIMIT;
        else {
            memcpy(candidateBytes,sourceBytes,found);
            memcpy(candidateBytes+found,newBytes,r.newSize);
            memcpy(candidateBytes+found+r.newSize,sourceBytes+found+r.oldSize,r.sourceSize-found-r.oldSize);
            if(size!=7771||!hashMatches(candidateBytes,size,r.expectedDigest)) status=CANDIDATE;
        }
    }
    return respond(r,1,status,size);
}
