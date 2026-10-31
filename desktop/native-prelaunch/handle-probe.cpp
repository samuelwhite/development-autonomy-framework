// Fixed valid-pipe health exchange. A3 case 01 never resumes this image.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
int main() {
    HANDLE in = GetStdHandle(STD_INPUT_HANDLE), out = GetStdHandle(STD_OUTPUT_HANDLE);
    HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
    if (GetFileType(in) != FILE_TYPE_PIPE || GetFileType(out) != FILE_TYPE_PIPE ||
        GetFileType(err) != FILE_TYPE_PIPE) return 70;
    const char health[] = "{\"probe\":\"valid_pipe_health\",\"value\":1}\n";
    DWORD written = 0;
    return WriteFile(out, health, sizeof(health) - 1, &written, nullptr) &&
        written == sizeof(health) - 1 ? 0 : 71;
}
