// Controller input: RecompFrontend's recompinput (SDL keyboard + game controllers) into N64 controller port 1.

#include "ultramodern/input.hpp"
#include "recompinput/recompinput.h"
#include "recompinput/input_state.h"
#include "recompinput/profiles.h"
#include "recompinput/players.h"

namespace somesay::rewind { bool active(); } // forward decl (dummy implementation in main.cpp)

// main.cpp defines this at global scope — declare here so poll_input can call it.
extern void somesay_debug_wait_while_paused();

namespace {
    void poll_input() {
        // P in main.cpp pauses the game here.
        somesay_debug_wait_while_paused();
        recompinput::poll_inputs();
    }

    ultramodern::input::connected_device_info_t get_connected_device_info(int controller_num) {
        if (controller_num == 0) {
            return { ultramodern::input::Device::Controller, ultramodern::input::Pak::RumblePak };
        }
        return { ultramodern::input::Device::None, ultramodern::input::Pak::None };
    }

    bool get_input(int controller_num, uint16_t* buttons, float* x, float* y) {
        if (somesay::rewind::active()) {
            *buttons = 0;
            *x = 0.0f;
            *y = 0.0f;
            return true;
        }
        return recompinput::profiles::get_n64_input(controller_num, buttons, x, y);
    }

    void set_rumble(int controller_num, bool on) {
        // Rumble passthrough — actual rumble control in main.cpp.
    }
}

namespace somesay::input {
    void init() {
        recompinput::players::set_single_player_mode(true);
    }

    void apply_rumble(bool game_held) {
        // Phase 5: no rumble implementation yet.
    }

    ultramodern::input::callbacks_t callbacks() {
        return ultramodern::input::callbacks_t{
            .poll_input = poll_input,
            .get_input = get_input,
            .set_rumble = set_rumble,
            .get_connected_device_info = get_connected_device_info,
        };
    }
}
