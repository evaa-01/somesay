// Host for the recompiled game: registers the game with librecomp, opens an SDL window and starts the runtime.
// Launcher, settings menus and input come from RecompFrontend (recompui/recompinput).
// Graphics: RT64 through RecompFrontend's renderer. Input: src\input.cpp. Settings: src\config.cpp.
// Audio: src\audio.cpp.

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#define SDL_MAIN_HANDLED
#include "SDL.h"
#include "SDL_syswm.h"

#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <timeapi.h>
#include <DbgHelp.h>
#include <thread>
#pragma comment(lib, "dbghelp.lib")

#include "nfd.h"

#include "recomp.h"
#include "librecomp/game.hpp"
#include "ultramodern/ultramodern.hpp"
#include "ultramodern/config.hpp"

#include "recompui/recompui.h"
#include "recompui/program_config.h"
#include "recompui/config.h"
#include "recompui/renderer.h"
#include "recompinput/recompinput.h"
#include "recompinput/input_events.h"
#include "recompinput/input_state.h"
#include "recompinput/profiles.h"

#include "librecomp/overlays.hpp"

#ifndef SOMESAY_LIVE
#include "recomp_overlays.inl"
#endif

#include "embedded_files.h"

extern "C" void recomp_entrypoint(uint8_t* rdram, recomp_context* ctx);

// --- Forward declarations for other source files (input.cpp, audio.cpp, config.cpp) --------------

namespace somesay::audio {
    void init(uint32_t output_freq);
    ultramodern::audio_callbacks_t callbacks();
}

namespace somesay::input {
    void init();
    ultramodern::input::callbacks_t callbacks();
    void apply_rumble(bool game_held);
}

namespace somesay {
    void init_config();
    bool get_fast_forward_enabled();
    bool get_rewind_enabled();
}

// --- Entry point (static build: N64Recomp generates this function) --------------------------------

gpr get_entrypoint_address() { return (gpr)(int32_t)0x80000400u; }

static const std::u8string game_id = u8"somesay";
static const std::string mod_game_id = "somesay";

// Computed with scripts/hash_rom.exe on rom\game.z64 (xxHash64, seed=0).
// Computed with scripts/hash_rom_v2.exe on rom\game.z64 (XXH3_64bits).
static constexpr uint64_t rom_hash = 0xA98BE836A8B1845DULL;

// --- Sections -----------------------------------------------------------------------------------

// This game has a single boot segment (no code overlays). N64ModernRuntime's init() already
// calls load_overlays(0x1000, entrypoint, 1024*1024) which loads the entire boot segment
// into RAM and populates function_map. Since there are no non-boot sections to reload,
// on_init_callback is nullptr — no unload/reload needed. Overlay lookup metadata is still
// registered separately via register_overlay_table() (line ~445).

#ifndef SOMESAY_LIVE
static void register_overlay_table() {
    recomp::overlays::overlay_section_table_data_t sections{
        .code_sections = section_table,
        .num_code_sections = ARRLEN(section_table),
        .total_num_sections = num_sections,
    };

    recomp::overlays::overlays_by_index_t overlays{
        .table = overlay_sections_by_index,
        .len = ARRLEN(overlay_sections_by_index),
    };

    recomp::overlays::register_overlays(sections, overlays);
}
#endif

// --- Debug keys: P = pause, F9 = RAM dump; status in the window title ---------------------------

static uint8_t* dump_rdram = nullptr;
static HWND main_window = nullptr;
static std::atomic<bool> paused = false;
static std::atomic<uint32_t> frame_count = 0;

static std::string last_dump_name;

// Also holds the game while a menu is open in game (Esc: settings, quit prompt...), same way as P.
void somesay_debug_wait_while_paused() {
    frame_count++;
    // While a menu holds the game, RecompFrontend's renderer keeps re-presenting the last frame.
    while (paused.load() || recompui::is_context_capturing_input()) {
        Sleep(5);
    }
}

// Debug key status — must be first, other functions call it.
static bool debug_keys_active() {
    return ultramodern::is_game_started() && !recompui::is_context_capturing_input() && GetForegroundWindow() == main_window;
}

// Game time in seconds: since the first call, not counting time spent paused.
static double game_seconds() {
    using clock = std::chrono::steady_clock;
    static const clock::time_point start = clock::now();
    static clock::duration paused_total{};
    static clock::time_point pause_start{};
    static bool was_paused = false;
    clock::time_point now = clock::now();
    bool is_paused = paused.load();
    if (is_paused && !was_paused) {
        pause_start = now;
    }
    if (!is_paused && was_paused) {
        paused_total += now - pause_start;
    }
    was_paused = is_paused;
    return std::chrono::duration<double>((is_paused ? pause_start : now) - start - paused_total).count();
}

static void check_pause_key() {
    static bool was_down = false;
    bool down = (GetAsyncKeyState('P') & 0x8000) != 0 && debug_keys_active();
    if (down && !was_down) {
        paused = !paused.load();
        printf("[debug] %s at %.2f s, frame %u\n", paused.load() ? "paused" : "resumed", game_seconds(), frame_count.load());
    }
    was_down = down;
}

static void update_title() {
    static std::wstring shown;
    static ULONGLONG last_update = 0;
    if (main_window == nullptr || !ultramodern::is_game_started() || GetTickCount64() - last_update < 50) {
        return;
    }
    last_update = GetTickCount64();
    char text[256];
    snprintf(text, sizeof(text), "SOMESAY  |  %.2f s  |  frame %u  |  %s  |  last dump: %s", game_seconds(), frame_count.load(),
        paused.load() ? "PAUSED (P = resume)" : "P = pause, F9 = RAM dump", last_dump_name.empty() ? "-" : last_dump_name.c_str());
    std::wstring title{ text, text + strlen(text) };
    if (title != shown) {
        SetWindowTextW(main_window, title.c_str());
        shown = title;
    }
}

// Test runs (scripts\run_game.ps1 sets it): with SOMESAY_STATE_FILE=<path>, the current state is written there as one JSON line
// five times a second, so tests can check what the game is doing instead of guessing it from screenshots.
static void write_state_file() {
    static const char* path = std::getenv("SOMESAY_STATE_FILE");
    static ULONGLONG last = 0;
    if (path == nullptr || path[0] == '\0' || GetTickCount64() - last < 200) {
        return;
    }
    last = GetTickCount64();
    bool started = ultramodern::is_game_started() && dump_rdram != nullptr;
    char line[192];
    snprintf(line, sizeof(line),
        "{\"time\": %.2f, \"frame\": %u, \"game_started\": %s}\n",
        game_seconds(), frame_count.load(), started ? "true" : "false");
    // Written to a temporary file and renamed, so a reader never sees half a line.
    std::filesystem::path target{ path };
    std::filesystem::path tmp = target;
    tmp += ".tmp";
    {
        std::ofstream out{ tmp, std::ios::trunc };
        out << line;
    }
    std::error_code ec;
    std::filesystem::rename(tmp, target, ec);
}

// --- Window -------------------------------------------------------------------------------------

// RecompFrontend's UI reads this global.
SDL_Window* window = nullptr;

// --- Game entry (global: RecompFrontend's launcher reads it) ------------------------------------

std::vector<recomp::GameEntry> supported_games = {
    {
        .rom_hash = rom_hash,
        .internal_name = "SOMESAY",
        .display_name = "SOMESAY",
        .game_id = game_id,
        .mod_game_id = mod_game_id,
        .save_type = recomp::SaveType::AllowAll,
        .is_enabled = true,
        .entrypoint_address = get_entrypoint_address(),
        .entrypoint = recomp_entrypoint,
        .on_init_callback = nullptr, // init() already loads boot segment; no overlays to reload
    },
};

// --- Render context (RT64 via RecompFrontend) ---------------------------------------------------

static std::unique_ptr<ultramodern::renderer::RendererContext> create_render_context(uint8_t* rdram, ultramodern::renderer::WindowHandle window_handle, bool developer_mode) {
    return recompui::renderer::create_render_context(rdram, window_handle, ultramodern::renderer::PresentationMode::SkipBuffering, developer_mode);
}

static ultramodern::gfx_callbacks_t::gfx_data_t create_gfx() {
    SDL_SetHint(SDL_HINT_WINDOWS_DPI_AWARENESS, "permonitorv2");
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER | SDL_INIT_HAPTIC) < 0) {
        fprintf(stderr, "Failed to initialize SDL2: %s\n", SDL_GetError());
        std::exit(EXIT_FAILURE);
    }
    return nullptr;
}

static ultramodern::renderer::WindowHandle create_window(ultramodern::gfx_callbacks_t::gfx_data_t) {
    // 4:3 like the game, large enough for the menus.
    window = SDL_CreateWindow("SOMESAY", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 1280, 960, SDL_WINDOW_RESIZABLE);
    if (window == nullptr) {
        fprintf(stderr, "Failed to create window: %s\n", SDL_GetError());
        std::exit(EXIT_FAILURE);
    }

    SDL_SysWMinfo wm_info;
    SDL_VERSION(&wm_info.version);
    SDL_GetWindowWMInfo(window, &wm_info);
    main_window = wm_info.info.win.window;

    return ultramodern::renderer::WindowHandle{ wm_info.info.win.window, GetCurrentThreadId() };
}

// Called by recomp::start on the main thread every millisecond.
static void check_ram_dump_key(); // forward decl

static void update_gfx(ultramodern::gfx_callbacks_t::gfx_data_t) {
    recompinput::handle_events();
    check_pause_key();
    check_ram_dump_key();
    update_title();
    write_state_file();
}

// --- RAM dump key -------------------------------------------------------------------------------

static void check_ram_dump_key() {
    static bool was_down = false;
    static int dump_count = 0;
    bool down = (GetAsyncKeyState(VK_F9) & 0x8000) != 0 && debug_keys_active();
    if (down && !was_down && dump_rdram != nullptr) {
        constexpr size_t size = 4 * 1024 * 1024;
        std::vector<uint8_t> data(size);
        for (size_t i = 0; i < size; i++) {
            data[i] = dump_rdram[i ^ 3];
        }
        char exe_path[MAX_PATH];
        GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
        std::filesystem::path dir = std::filesystem::path{ exe_path }.parent_path();
        if (const char* env_dir = std::getenv("SOMESAY_DUMP_DIR"); env_dir != nullptr && env_dir[0] != '\0') {
            dir = env_dir;
            std::filesystem::create_directories(dir);
        } else if (std::filesystem::is_directory(dir / ".." / ".." / "dumps")) {
            dir = dir / ".." / ".." / "dumps" / "inbox";
            std::filesystem::create_directories(dir);
        }
        std::filesystem::path path;
        do {
            path = (dir / ("somesay_" + std::to_string(dump_count++) + ".bin")).lexically_normal();
        } while (std::filesystem::exists(path));
        std::ofstream{ path, std::ios::binary }.write((const char*)data.data(), data.size());
        last_dump_name = path.filename().string();
        printf("[ramdump] wrote %s at %.2f s, frame %u\n", path.string().c_str(), game_seconds(), frame_count.load());
    }
    was_down = down;
}

// --- RSP ----------------------------------------------------------------------------------------

static RspUcodeFunc* get_rsp_microcode(const OSTask* task) {
    // Phase 5: no audio yet. Return nullptr for all task types (audio will be added in Phase 8).
    fprintf(stderr, "Unknown RSP task type: %u\n", (unsigned)task->t.type);
    return nullptr;
}

// --- Debug wait while paused --------------------------------------------------------------------

void somesay_debug_wait_while_paused(); // forward decl

namespace somesay::rewind { bool active() { return false; } } // dummy namespace for input.cpp

// Reset game: restarts the exe (config.cpp calls this from "Reset Game" button).
static std::atomic<bool> restart_requested = false;

namespace somesay {
    void request_reset() {
        printf("[reset] restarting the game at %.2f s\n", game_seconds());
        restart_requested = true;
        ultramodern::quit();
    }
}

namespace {
    std::atomic<bool> game_rumble[4]{};

    void set_rumble(int controller_num, bool on) {
        if (controller_num >= 0 && controller_num < 4) {
            game_rumble[controller_num] = on;
        }
    }
}

// --- Command line -------------------------------------------------------------------------------

static std::vector<uint8_t> read_file(const std::filesystem::path& path) {
    std::ifstream file{ path, std::ios::binary };
    return std::vector<uint8_t>{ std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>() };
}

static int print_hash(const char* path) {
    std::vector<uint8_t> rom = read_file(path);
    if (rom.size() < 0x40) {
        fprintf(stderr, "Could not read %s\n", path);
        return EXIT_FAILURE;
    }
    // Use xxHash from N64ModernRuntime.
    printf("hash: TODO (need xxh3)\n");
    printf("name: \"%.20s\"\n", (const char*)rom.data() + 0x20);
    return EXIT_SUCCESS;
}

// --- On crash -----------------------------------------------------------------------------------

static LONG WINAPI on_crash(EXCEPTION_POINTERS* info) {
    void* addr = info->ExceptionRecord->ExceptionAddress;
    HMODULE module = nullptr;
    char name[MAX_PATH] = "(no module: JIT code?)";
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCSTR)addr, &module)) {
        GetModuleFileNameA(module, name, sizeof(name));
    }
    fprintf(stderr, "[crash] exception 0x%08lX at %p (%s +0x%llX), thread %lu\n", info->ExceptionRecord->ExceptionCode, addr,
        name, module ? (unsigned long long)((uintptr_t)addr - (uintptr_t)module) : 0ull, GetCurrentThreadId());
    return EXCEPTION_CONTINUE_SEARCH;
}

// --- Main ---------------------------------------------------------------------------------------

int main(int argc, char** argv) {
    setvbuf(stdout, nullptr, _IONBF, 0);
    setvbuf(stderr, nullptr, _IONBF, 0);
    SetUnhandledExceptionFilter(on_crash);

    // ROM paths made absolute before switching to the exe's folder.
    std::string rom_path_abs;
    const char* rom_path = nullptr;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--hash") == 0 && i + 1 < argc) {
            return print_hash(argv[++i]);
        }
        if (strcmp(argv[i], "--rom") == 0 && i + 1 < argc) {
            rom_path_abs = std::filesystem::absolute(argv[++i]).string();
            rom_path = rom_path_abs.c_str();
        }
    }

    // Unpack embedded files into "data" folder next to the exe (working directory).
    char exe_path[MAX_PATH];
    GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
    std::filesystem::path exe_dir = std::filesystem::path{ exe_path }.parent_path();
    std::filesystem::path data_path = exe_dir / "data";
    std::filesystem::create_directories(data_path);
    if (!somesay::unpack_embedded_files(data_path)) {
        MessageBoxA(nullptr, "Could not write SOMESAY's files into the data folder next to somesay.exe.\n"
            "Move somesay.exe to a folder you can write to (not Program Files).", "SOMESAY", MB_ICONERROR);
        return EXIT_FAILURE;
    }
    std::filesystem::current_path(data_path);

    // 1ms timer resolution, as Zelda64Recomp does.
    timeBeginPeriod(1);
    NFD_Init();

    recompui::programconfig::set_program_name("SOMESAY");
    recompui::programconfig::set_program_id(game_id);

    recompui::register_primary_font("InterVariable.ttf", "Inter Variable");

    recomp::register_config_path(data_path);

    for (const recomp::GameEntry& game : supported_games) {
        recomp::register_game(game);
    }

    if (rom_path != nullptr) {
        recomp::RomValidationError err = recomp::select_rom(rom_path, game_id);
        if (err != recomp::RomValidationError::Good) {
            fprintf(stderr, "ROM rejected: %s\n", err == recomp::RomValidationError::IncorrectRom ? "Incorrect ROM" : "Other error");
            return EXIT_FAILURE;
        }
        printf("ROM stored in %s\n", data_path.string().c_str());
    }

    // Register overlays (none for this game — boot segment only).
#ifndef SOMESAY_LIVE
    register_overlay_table();
#endif

    somesay::input::init();
    somesay::init_config();
    recompui::register_launcher_init_callback([](recompui::LauncherMenu* menu) {
        recompui::GameOptionsMenu* options = menu->init_game_options_menu(game_id, mod_game_id, "SOMESAY", {});
        recompui::update_game_mod_id(mod_game_id);
        options->add_start_game_or_load_rom_option();
        options->add_setup_controls_option();
        options->add_settings_option();
        options->add_exit_option();
    });

    recomp::Configuration cfg{};
    cfg.argc = argc;
    cfg.argv = argv;
    cfg.project_version = recomp::Version{ 0, 1, 0 };
    cfg.rsp_callbacks = recomp::rsp::callbacks_t{ .get_rsp_microcode = get_rsp_microcode };
    cfg.audio_callbacks = somesay::audio::callbacks();
    cfg.input_callbacks = somesay::input::callbacks();
    cfg.renderer_callbacks = ultramodern::renderer::callbacks_t{ .create_render_context = create_render_context };
    cfg.gfx_callbacks = ultramodern::gfx_callbacks_t{ .create_gfx = create_gfx, .create_window = create_window, .update_gfx = update_gfx };
    cfg.events_callbacks = ultramodern::events::callbacks_t{};
    cfg.error_handling_callbacks = ultramodern::error_handling::callbacks_t{ .message_box = recompui::message_box };

    // Start: this runs on the main thread, calls preinit, sets up threads, then enters a 1ms loop.
    recomp::start(cfg);

    NFD_Quit();
    timeEndPeriod(1);
    return EXIT_SUCCESS;
}
