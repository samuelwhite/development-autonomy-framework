#include "readiness.h"
#include <string>
#include <stdio.h>
int main() {
    const std::string record = "{\"probe\":\"hold_ready\",\"status\":\"observed\",\"code\":0}";
    unsigned tests = 0;
    auto test = [&](const std::string& input, bool expected) {
        ++tests;
        if (readyRecord(input.data(), input.size()) != expected) return false;
        return true;
    };
    if (!test(record + "\n", true) || !test(record + "\r\n", true)) return 1;
    for (const auto& invalid : {std::string(), record, record + "\r", record + "\r\r\n",
         "prefix" + record + "\n", record + "suffix\n", " " + record + "\n",
         record + " \n", record + "\ntrailing", record + std::string("\0\n", 2),
         std::string("{\"probe\":\"hold_ready\",\"status\":\"observed\",\"code\":1}\n"),
         std::string("{\"probe\":\"other\",\"status\":\"observed\",\"code\":0}\n"),
         std::string("{\"probe\":\"hold_ready\",\"status\":\"observed\",\"code\":0,\"extra\":1}\n")})
        if (!test(invalid, false)) return 2;
    for (const auto& ending : {std::string("\n"), std::string("\r\n")}) {
        std::string stream = "unrelated\n" + record + ending;
        for (size_t split = 0; split < stream.size(); ++split) {
            size_t cursor = 0; ++tests;
            if (scanReady(stream.data(), split, cursor)) return 3;
            if (!scanReady(stream.data(), stream.size(), cursor)) return 4;
            if (scanReady(stream.data(), stream.size(), cursor)) return 5;
        }
    }
    printf("Exact diagnostic readiness framing: %u checks passed\n", tests);
    return 0;
}
