// Settings menu (RecompFrontend): General tab with fast-forward/rewind toggles. Graphics, Controls and Sound tabs
// are created by the standard RecompFrontend helpers. The settings are saved as <tab id>.json in the runtime's
// config path (runtime\build\data), next to the stored ROM and the saves.

#include <filesystem>

#include "librecomp/game.hpp"
#include "ultramodern/config.hpp"
#include "recompui/config.h"
#include "recompinput/recompinput.h"
#include "recompinput/input_mapping.h"
#include "recompui/recompui.h"
#include "elements/ui_button.h"
#include "elements/ui_container.h"
#include "elements/ui_label.h"
#include "config/ui_config_page_options_menu.h"

namespace somesay { void request_reset(); } // main.cpp

namespace {
    void set_control_defaults() {
        using namespace recompinput;
        auto key = [](SDL_Scancode k) { return InputField::keyboard(k); };

        set_default_mapping_for_keyboard(GameInput::A,          { key(SDL_SCANCODE_X) });
        set_default_mapping_for_keyboard(GameInput::B,          { key(SDL_SCANCODE_C) });
        set_default_mapping_for_keyboard(GameInput::Z,          { key(SDL_SCANCODE_Z) });
        set_default_mapping_for_keyboard(GameInput::START,      { key(SDL_SCANCODE_RETURN) });
        set_default_mapping_for_keyboard(GameInput::L,          { key(SDL_SCANCODE_A) });
        set_default_mapping_for_keyboard(GameInput::R,          { key(SDL_SCANCODE_S) });
        set_default_mapping_for_keyboard(GameInput::C_UP,       { key(SDL_SCANCODE_I) });
        set_default_mapping_for_keyboard(GameInput::C_DOWN,     { key(SDL_SCANCODE_K) });
        set_default_mapping_for_keyboard(GameInput::C_LEFT,     { key(SDL_SCANCODE_J) });
        set_default_mapping_for_keyboard(GameInput::C_RIGHT,    { key(SDL_SCANCODE_L) });
        set_default_mapping_for_keyboard(GameInput::DPAD_UP,    { key(SDL_SCANCODE_T) });
        set_default_mapping_for_keyboard(GameInput::DPAD_DOWN,  { key(SDL_SCANCODE_G) });
        set_default_mapping_for_keyboard(GameInput::DPAD_LEFT,  { key(SDL_SCANCODE_F) });
        set_default_mapping_for_keyboard(GameInput::DPAD_RIGHT, { key(SDL_SCANCODE_H) });
        set_default_mapping_for_keyboard(GameInput::X_AXIS_NEG, { key(SDL_SCANCODE_LEFT) });
        set_default_mapping_for_keyboard(GameInput::X_AXIS_POS, { key(SDL_SCANCODE_RIGHT) });
        set_default_mapping_for_keyboard(GameInput::Y_AXIS_POS, { key(SDL_SCANCODE_UP) });
        set_default_mapping_for_keyboard(GameInput::Y_AXIS_NEG, { key(SDL_SCANCODE_DOWN) });

        // Controller: stick = left stick, A = south, B = west, Z = left trigger.
        set_default_mapping_for_controller(GameInput::R, { InputField::controller_digital(SDL_CONTROLLER_BUTTON_RIGHTSHOULDER) });
        set_default_mapping_for_controller(GameInput::C_DOWN, { InputField::controller_analog(SDL_CONTROLLER_AXIS_RIGHTY, true) });

        // Fast-forward and rewind (main.cpp).
        set_default_mapping_for_keyboard(GameInput::FAST_FORWARD, { key(SDL_SCANCODE_TAB) });
        set_default_mapping_for_keyboard(GameInput::REWIND, { key(SDL_SCANCODE_BACKSPACE) });
        set_default_mapping_for_controller(GameInput::FAST_FORWARD, { InputField::controller_analog(SDL_CONTROLLER_AXIS_TRIGGERRIGHT, true) });
        set_default_mapping_for_controller(GameInput::REWIND, { InputField::controller_digital(SDL_CONTROLLER_BUTTON_LEFTSTICK) });
        set_game_input_description(GameInput::FAST_FORWARD, "Hold to run the game at double speed (if switched on in the General tab).");
        set_game_input_description(GameInput::REWIND, "Hold during missions to run the game backwards, up to 10 seconds (if switched on in the General tab).");
    }
}

namespace somesay {
    const std::string fast_forward_option = "fast_forward";

    // Fast-forward on/off from the General tab.
    bool get_fast_forward_enabled() {
        return std::get<bool>(recompui::config::get_general_config().get_option_value(fast_forward_option));
    }

    const std::string rewind_option = "rewind";

    // Rewind on/off from the General tab (rewind.cpp).
    bool get_rewind_enabled() {
        return std::get<bool>(recompui::config::get_general_config().get_option_value(rewind_option));
    }

    void init_config() {
        recompui::config::GeneralTabOptions general_options{};
        general_options.has_rumble_strength = true;
        recomp::config::Config& general_config = recompui::config::create_general_tab(general_options);
        // Fixed 2x: user found flicker at higher speeds.
        general_config.add_bool_option(fast_forward_option, "Fast-Forward",
            "Hold the Fast-Forward button (Controls tab; default: right trigger, keyboard Tab) to run the game at double speed. "
            "Sound is muted meanwhile.",
            true);
        general_config.add_bool_option(rewind_option, "Rewind",
            "Hold the Rewind button (Controls tab; default: left stick click, keyboard Backspace) during missions to run the game backwards, up to 10 seconds. "
            "Sound is muted meanwhile.",
            true);

        // Hide the stock General tab and replace it with one that also has a Reset Game button.
        recompui::config::set_tab_visible(recompui::config::general::id, false);
        recompui::config::create_tab("General", "general_page", [](recompui::ContextId ctx, recompui::Element* parent) {
            auto* page = ctx.create_element<recompui::ConfigPageOptionsMenu>(parent, &recompui::config::get_general_config(), true);
            page->set_as_navigation_container(recompui::NavigationType::Vertical);
            recompui::ConfigHeaderFooter* footer = page->add_footer();
            auto* reset = ctx.create_element<recompui::Button>(footer->get_left(), "Reset Game", recompui::ButtonStyle::Danger,
                recompui::ButtonSize::Medium);
            reset->set_width(220.0f);
            reset->add_pressed_callback([]() {
                recompui::open_choice_prompt("Reset the game?", "The game starts again from the beginning.",
                    "Reset", "Cancel", []() { somesay::request_reset(); }, []() {},
                    recompui::ButtonStyle::Danger, recompui::ButtonStyle::Tertiary, true);
            });
        });

        recompui::config::create_graphics_tab();
        set_control_defaults();
        recompui::config::create_controls_tab();
        recompui::config::create_sound_tab();

        // Graphics defaults for a new install (no graphics.json yet): the original N64 picture, except resolution.
        namespace graphics = recompui::config::graphics;
        namespace renderer = ultramodern::renderer;
        bool first_run = !std::filesystem::exists(recomp::get_config_path() / (graphics::id + ".json"));

        recompui::config::finalize();

        if (first_run) {
            recomp::config::Config& graphics_config = recompui::config::get_graphics_config();
            graphics_config.set_option_value(graphics::options::res_option, uint32_t(renderer::Resolution::Original2x));
            graphics_config.set_option_value(graphics::options::ar_option, uint32_t(renderer::AspectRatio::Original));
            graphics_config.set_option_value(graphics::options::hr_option, uint32_t(renderer::HUDRatioMode::Original));
            graphics_config.set_option_value(graphics::options::rr_option, uint32_t(renderer::RefreshRate::Original));
            graphics_config.set_option_value(graphics::options::msaa_option, uint32_t(renderer::Antialiasing::None));
            graphics_config.save_config();
            graphics_config.load_config(); // applies the saved settings to the renderer config
        }
    }
}
