// Redirect only this research executable's imported app-data lookup.
// Loaded before the runner's entrypoint by Aurie's native-module loader.
#include <windows.h>
#include <shlobj.h>
#include <cstring>
#include <cstdio>

static decltype(&SHGetFolderPathW) original_folder_path = nullptr;
static wchar_t profile_path[MAX_PATH]{};
static decltype(&ExitProcess) original_exit = nullptr;

static void log_exit(DWORD code) {
    wchar_t path[32768]{};
    DWORD length = GetEnvironmentVariableW(L"HOLOCURE_TRACE_DIR", path, 32768);
    if (!length || length > 32740) return;
    wcscat_s(path, L"\\exit-stack.txt");
    HANDLE file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    char text[512];
    DWORD written;
    int count = sprintf_s(text, "ExitProcess(%lu)\r\n", code);
    WriteFile(file, text, count, &written, nullptr);
    void* frames[48]{};
    USHORT frame_count = CaptureStackBackTrace(0, 48, frames, nullptr);
    for (USHORT i = 0; i < frame_count; ++i) {
        HMODULE module = nullptr;
        char name[MAX_PATH]{};
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCSTR>(frames[i]), &module);
        GetModuleFileNameA(module, name, MAX_PATH);
        char* base_name = strrchr(name, '\\');
        count = sprintf_s(text, "%s+0x%llx\r\n", base_name ? base_name + 1 : name,
                          reinterpret_cast<ULONG_PTR>(frames[i]) - reinterpret_cast<ULONG_PTR>(module));
        WriteFile(file, text, count, &written, nullptr);
    }
    CloseHandle(file);
}

static void WINAPI research_exit(UINT code) {
    log_exit(code);
    original_exit(code);
}

static LONG CALLBACK observe_exception(EXCEPTION_POINTERS* info) {
    if (info->ExceptionRecord->ExceptionCode != EXCEPTION_ACCESS_VIOLATION)
        return EXCEPTION_CONTINUE_SEARCH;
    wchar_t path[32768]{};
    DWORD length = GetEnvironmentVariableW(L"HOLOCURE_TRACE_DIR", path, 32768);
    if (!length || length > 32740) return EXCEPTION_CONTINUE_SEARCH;
    wcscat_s(path, L"\\exception.txt");
    HANDLE file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file != INVALID_HANDLE_VALUE) {
        char text[1024];
        DWORD written;
        auto* c = info->ContextRecord;
        int count = sprintf_s(text,
            "ACCESS_VIOLATION\r\nRIP=%llx GameBase=%llx\r\nRAX=%llx RBX=%llx RCX=%llx RDX=%llx\r\nR8=%llx R9=%llx RSP=%llx\r\nAccess=%llu Address=%llx\r\n",
            c->Rip, reinterpret_cast<ULONG_PTR>(GetModuleHandleW(nullptr)), c->Rax, c->Rbx, c->Rcx, c->Rdx,
            c->R8, c->R9, c->Rsp, info->ExceptionRecord->ExceptionInformation[0], info->ExceptionRecord->ExceptionInformation[1]);
        WriteFile(file, text, count, &written, nullptr);
        CloseHandle(file);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static HRESULT WINAPI research_folder(HWND window, int folder, HANDLE token,
                                      DWORD flags, LPWSTR output) {
    const int id = folder & 0xff;
    if (id == CSIDL_LOCAL_APPDATA || id == CSIDL_APPDATA) {
        wcscpy_s(output, MAX_PATH, profile_path);
        return S_OK;
    }
    return original_folder_path(window, folder, token, flags, output);
}

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID) {
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DWORD length = GetEnvironmentVariableW(L"HOLOCURE_PROFILE_DIR", profile_path, MAX_PATH);
    if (!length || length >= MAX_PATH) ExitProcess(90);
    AddVectoredExceptionHandler(0, observe_exception);
    auto* base = reinterpret_cast<unsigned char*>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    auto directory = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    auto* imports = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + directory.VirtualAddress);
    bool patched = false;
    for (; imports->Name; ++imports) {
        if (!imports->OriginalFirstThunk) continue;
        auto* names = reinterpret_cast<IMAGE_THUNK_DATA64*>(base + imports->OriginalFirstThunk);
        auto* slots = reinterpret_cast<IMAGE_THUNK_DATA64*>(base + imports->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++slots) {
            if (IMAGE_SNAP_BY_ORDINAL64(names->u1.Ordinal)) continue;
            auto* name = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
            if (!strcmp(reinterpret_cast<char*>(name->Name), "ExitProcess")) {
                original_exit = reinterpret_cast<decltype(original_exit)>(slots->u1.Function);
                DWORD old_protection;
                if (VirtualProtect(&slots->u1.Function, sizeof(void*), PAGE_READWRITE, &old_protection)) {
                    slots->u1.Function = reinterpret_cast<ULONGLONG>(&research_exit);
                    VirtualProtect(&slots->u1.Function, sizeof(void*), old_protection, &old_protection);
                }
                continue;
            }
            if (strcmp(reinterpret_cast<char*>(name->Name), "SHGetFolderPathW")) continue;
            original_folder_path = reinterpret_cast<decltype(original_folder_path)>(slots->u1.Function);
            DWORD old_protection;
            if (!VirtualProtect(&slots->u1.Function, sizeof(void*), PAGE_READWRITE, &old_protection))
                ExitProcess(91);
            slots->u1.Function = reinterpret_cast<ULONGLONG>(&research_folder);
            VirtualProtect(&slots->u1.Function, sizeof(void*), old_protection, &old_protection);
            patched = true;
        }
    }
    // Never continue into the game if the profile isolation was not installed.
    if (!patched) ExitProcess(92);
    return TRUE;
}
