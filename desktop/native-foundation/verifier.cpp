#include "wire.h"
// Independent range checker; does not link or call the producer transformation.
int main() {
    Request r{};Failure status=receive(r,2);size_t offset=0,matches=0;
    if(status==OK) {
        // Independent scan, including overlapping occurrences.
        for(size_t i=0;i<r.sourceSize;++i) {
            size_t j=0;
            while(j<r.oldSize&&i+j<r.sourceSize&&sourceBytes[i+j]==oldBytes[j]) ++j;
            if(j==r.oldSize) {offset=i;++matches;}
        }
        if(matches!=1) status=OCCURRENCE;
        else status=validateBytes(r);
    }
    if(status==OK) {
        size_t end=offset+r.newSize, suffix=r.sourceSize-offset-r.oldSize;
        if(r.candidateSize!=7771||end+suffix!=r.candidateSize) status=CANDIDATE;
        else {
            for(size_t i=0;i<r.candidateSize;++i) {
                unsigned char expected;
                if(i<offset) expected=sourceBytes[i];
                else if(i<end) expected=newBytes[i-offset];
                else expected=sourceBytes[offset+r.oldSize+i-end];
                if(candidateBytes[i]!=expected) {status=CANDIDATE;break;}
            }
            if(!hashMatches(candidateBytes,r.candidateSize,r.expectedDigest)) status=CANDIDATE;
        }
    }
    return respond(r,2,status,r.candidateSize);
}
