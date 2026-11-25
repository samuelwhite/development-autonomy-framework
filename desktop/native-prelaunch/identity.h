// Candidate prelaunch primitive. Standalone qualification only; never packaged.
#pragma once
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <psapi.h>
#include <filesystem>
#include <string>
#include <vector>
#include <memory>
#include <stdexcept>
#include "../native-foundation/sha256.h"
#pragma comment(lib, "psapi.lib")

namespace prelaunch {
struct Failure { const char* stage; DWORD error; };
inline void require(bool ok, const char* stage) {
    if (!ok) throw Failure{stage, GetLastError()};
}
struct Handle {
    HANDLE h = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE value) : h(value) {}
    ~Handle() { if (h && h != INVALID_HANDLE_VALUE) CloseHandle(h); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};
inline std::string digest(const std::vector<unsigned char>& data) {
    unsigned char hash[32]; sha256(data.data(), data.size(), hash);
    const char hex[] = "0123456789abcdef"; std::string result;
    for (auto b : hash) { result += hex[b >> 4]; result += hex[b & 15]; }
    return result;
}
inline FILE_ID_INFO identity(HANDLE h) {
    FILE_ID_INFO id{};
    require(GetFileInformationByHandleEx(h, FileIdInfo, &id, sizeof(id)), "file_id");
    return id;
}
inline bool equal(const FILE_ID_INFO& a, const FILE_ID_INFO& b) {
    return a.VolumeSerialNumber == b.VolumeSerialNumber &&
        !memcmp(a.FileId.Identifier, b.FileId.Identifier, sizeof(a.FileId.Identifier));
}
inline std::wstring name(HANDLE h, DWORD volume = VOLUME_NAME_DOS) {
    wchar_t buffer[32768];
    const DWORD n = GetFinalPathNameByHandleW(h, buffer, 32768, FILE_NAME_NORMALIZED | volume);
    require(n && n < 32768, "final_path");
    return std::wstring(buffer, n);
}
inline void syntax(const std::wstring& path) {
    require(path.size() > 3 && path.size() < 240 && path[0] >= L'A' &&
        path[0] <= L'Z' && path[1] == L':' && path[2] == L'\\', "path_syntax");
    size_t start = 3;
    for (size_t i = 3; i <= path.size(); ++i) {
        if (i != path.size() && path[i] != L'\\') {
            const wchar_t c = path[i];
            require(c >= 32 && c < 127 && c != L':' && c != L'/' && c != L'~' &&
                c != L'?' && c != L'*' && c != L'"' && c != L'<' && c != L'>' && c != L'|', "path_syntax");
            continue;
        }
        require(i > start && path[i - 1] != L'.' && path[i - 1] != L' ', "path_component");
        start = i + 1;
    }
}
class ImagePin {
    std::vector<std::unique_ptr<Handle>> chain;
    std::vector<FILE_ID_INFO> ids;
    std::wstring path, ntPath;
    std::string expected;
    size_t length;
    std::vector<unsigned char> read() const {
        HANDLE h = chain.back()->h;
        LARGE_INTEGER size{}, zero{};
        require(GetFileSizeEx(h, &size) && size.QuadPart == length && length <= 1048576,
            "image_length");
        require(SetFilePointerEx(h, zero, nullptr, FILE_BEGIN), "image_seek");
        std::vector<unsigned char> data(length); DWORD n = 0;
        require(ReadFile(h, data.data(), (DWORD)length, &n, nullptr) && n == length, "image_read");
        return data;
    }
public:
    ImagePin(const std::wstring& file, const std::string& hash, size_t bytes)
        : path(file), expected(hash), length(bytes) {
        syntax(file);
        // Pin each parent before resolving its next component. Deny data-write
        // and delete sharing throughout the chain, including the image itself.
        std::vector<std::wstring> paths{file.substr(0, 3)};
        for (size_t i = 3; i < file.size(); ++i)
            if (file[i] == L'\\') paths.push_back(file.substr(0, i));
        paths.push_back(file);
        for (size_t i = 0; i < paths.size(); ++i) {
            const bool directory = i + 1 < paths.size();
            auto handle = std::make_unique<Handle>(CreateFileW(paths[i].c_str(), GENERIC_READ,
                FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT | (directory ? FILE_FLAG_BACKUP_SEMANTICS : 0), nullptr));
            require(handle->h != INVALID_HANDLE_VALUE, "pin_open");
            BY_HANDLE_FILE_INFORMATION info{};
            require(GetFileType(handle->h) == FILE_TYPE_DISK &&
                GetFileInformationByHandle(handle->h, &info), "regular_file");
            require(!(info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) &&
                !!(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == directory, "reparse_or_type");
            require(directory || info.nNumberOfLinks == 1, "hard_link");
            require(name(handle->h) == L"\\\\?\\" + paths[i], "canonical_path");
            ids.push_back(identity(handle->h)); chain.push_back(std::move(handle));
        }
        ntPath = name(chain.back()->h, VOLUME_NAME_NT);
        recheck();
    }
    void recheck() const {
        for (size_t i = 0; i < chain.size(); ++i) {
            BY_HANDLE_FILE_INFORMATION info{};
            require(GetFileInformationByHandle(chain[i]->h, &info), "recheck_metadata");
            require(!(info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) &&
                equal(ids[i], identity(chain[i]->h)), "identity_changed");
            require(i + 1 < chain.size() || info.nNumberOfLinks == 1, "hard_link");
        }
        require(name(chain.back()->h) == L"\\\\?\\" + path, "path_changed");
        require(digest(read()) == expected, "image_digest");
    }
    void verifySuspended(HANDLE process) const {
        // No child assertion is used. Query the OS-owned process pathname and
        // enumerate MEM_IMAGE allocations while the initial thread is suspended.
        wchar_t image[32768]; DWORD n = 32768;
        require(QueryFullProcessImageNameW(process, 0, image, &n) &&
            std::wstring(image, n) == path, "process_image_path");
        n = 32768;
        require(QueryFullProcessImageNameW(process, PROCESS_NAME_NATIVE, image, &n) &&
            std::wstring(image, n) == ntPath, "process_native_path");
        unsigned matches = 0; uintptr_t at = 0; MEMORY_BASIC_INFORMATION info{};
        while (VirtualQueryEx(process, (void*)at, &info, sizeof(info)) == sizeof(info)) {
            if (info.Type == MEM_IMAGE && info.BaseAddress == info.AllocationBase) {
                n = GetMappedFileNameW(process, info.AllocationBase, image, 32768);
                require(n && n < 32768, "mapped_image_name");
                if (std::wstring(image, n) == ntPath) ++matches;
            }
            const uintptr_t next = (uintptr_t)info.BaseAddress + info.RegionSize;
            require(next > at, "memory_walk"); at = next;
        }
        require(GetLastError() == ERROR_INVALID_PARAMETER && matches == 1, "mapped_image_identity");
        // Reopen while the original complete chain remains pinned. Its file ID
        // and exact bytes must still identify the approved backing file.
        Handle actual(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
            OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        require(actual.h != INVALID_HANDLE_VALUE && equal(identity(actual.h), ids.back()), "launched_file_id");
        recheck();
    }
};
} // namespace prelaunch
