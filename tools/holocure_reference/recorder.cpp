#include <YYToolkit/YYTK_Shared.hpp>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>
#include <cmath>

using namespace Aurie;
using namespace YYTK;
static YYTKInterface* api = nullptr;
static std::ofstream trace;
static std::set<std::string> event_names;
static uint64_t event_sequence = 0, presents = 0;
static bool captured_catalog = false;
static fs::path trace_directory;
static bool screenshot_requested = false;
static bool held_keys[256]{};
static uint64_t gameplay_tick = 0;
static bool in_gameplay = false;

static const char* TRACKED_OBJECTS[] = {
    "obj_Player", "obj_Enemy", "obj_BaseEnemy", "obj_Attack",
    "obj_EXP", "obj_EXPAbsorb", "obj_ItemCrate", "obj_damageText",
    "obj_EnemySpawn", "obj_EnemySpawner", "obj_StageManager",
    "obj_PlayerManager", "obj_MobManager", "obj_FandomManager",
    "obj_InputManager", "obj_AttackController"
};
static constexpr int TRACKED_COUNT = sizeof(TRACKED_OBJECTS) / sizeof(TRACKED_OBJECTS[0]);

static const int ACTION_KEYS[] = {87, 83, 65, 68, 32, 16, 17};
static constexpr int ACTION_COUNT = 7;

static std::string quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char ch : value) {
        if (ch == '"' || ch == '\\') out << '\\' << ch;
        else if (ch < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(ch);
        else out << ch;
    }
    out << '"';
    return out.str();
}

static std::string value_json(const RValue& value, int depth = 0) {
    std::ostringstream out;
    switch (value.m_Kind) {
        case VALUE_REAL: case VALUE_INT32: case VALUE_INT64: case VALUE_BOOL: {
            double number = value.ToDouble();
            if (std::isfinite(number)) out << std::setprecision(17) << number;
            else out << "null";
            return out.str();
        }
        case VALUE_STRING: return quote(value.ToString());
        case VALUE_REF: {
            // Modern GameMaker represents ds_map handles as typed references.
            // Let the runner inspect these; never reinterpret a handle as a pointer.
            const std::string display = api->CallBuiltin("string", {value}).ToString();
            if (depth < 5 && display.find("ds_map") != std::string::npos &&
                api->CallBuiltin("ds_exists", {value, 1}).ToBoolean()) {
                out << '{';
                auto key = api->CallBuiltin("ds_map_find_first", {value});
                bool first = true;
                for (unsigned i = 0; key.m_Kind != VALUE_UNDEFINED && i < 4096; ++i) {
                    if (!first) out << ',';
                    first = false;
                    auto name = api->CallBuiltin("string", {key}).ToString();
                    out << quote(name) << ':' << value_json(api->CallBuiltin("ds_map_find_value", {value, key}), depth + 1);
                    key = api->CallBuiltin("ds_map_find_next", {value, key});
                }
                out << '}';
                return out.str();
            }
            return "{\"_kind\":\"ref\",\"display\":" + quote(display) + "}";
        }
        case VALUE_OBJECT: {
            if (depth >= 5) return "{\"_kind\":\"object\",\"_truncated\":true}";
            out << '{';
            bool first = true;
            unsigned count = 0;
            api->EnumInstanceMembers(value, [&](const char* name, RValue* member) {
                if (count++ >= 4096) return true;
                if (!first) out << ',';
                first = false;
                out << quote(name) << ':' << value_json(*member, depth + 1);
                return false;
            });
            out << '}';
            return out.str();
        }
        case VALUE_ARRAY: {
            if (depth >= 5) return "{\"_kind\":\"array\",\"_truncated\":true}";
            RValue copy = value;
            size_t size = 0;
            if (!AurieSuccess(api->GetArraySize(copy, size))) return "null";
            out << "{\"_kind\":\"array\",\"length\":" << size << ",\"values\":[";
            for (size_t i = 0; i < size && i < 128; ++i) {
                if (i) out << ',';
                RValue* member = nullptr;
                out << (AurieSuccess(api->GetArrayEntry(copy, i, member)) ? value_json(*member, depth + 1) : "null");
            }
            out << "]}";
            return out.str();
        }
        default: return "{\"_kind\":" + quote(value.GetKindName()) + "}";
    }
}

static std::string action_json() {
    std::ostringstream out;
    out << '[';
    for (int i = 0; i < ACTION_COUNT; ++i) {
        if (i) out << ',';
        out << (held_keys[ACTION_KEYS[i]] ? 1 : 0);
    }
    out << ']';
    return out.str();
}

static std::string builtin_json(CInstance* instance, const char* name) {
    RValue value;
    if (AurieSuccess(api->GetBuiltin(name, instance, NULL_INDEX, value))) {
        switch (value.m_Kind) {
            case VALUE_REAL: case VALUE_INT32: case VALUE_INT64: case VALUE_BOOL: {
                double number = value.ToDouble();
                if (std::isfinite(number)) {
                    std::ostringstream out;
                    out << std::setprecision(17) << number;
                    return out.str();
                }
                return "null";
            }
            case VALUE_STRING: return quote(value.ToString());
            default: return "null";
        }
    }
    return "null";
}

static void snapshot_world() {
    trace << "{\"kind\":\"canonical_tick\",\"tick\":" << gameplay_tick
          << ",\"action\":" << action_json()
          << ",\"instances\":[";
    bool first = true;
    for (int i = 0; i < TRACKED_COUNT; ++i) {
        api->InvokeWithObject(RValue(TRACKED_OBJECTS[i]), [&](CInstance* self, CInstance*) {
            if (!first) trace << ',';
            first = false;
            RValue obj_idx_val;
            int32_t obj_idx = -1;
            if (AurieSuccess(api->GetBuiltin("object_index", self, NULL_INDEX, obj_idx_val)))
                obj_idx = obj_idx_val.ToInt32();
            std::string obj_name = TRACKED_OBJECTS[i];
            if (obj_idx >= 0) {
                auto name_val = api->CallBuiltin("object_get_name", {obj_idx_val});
                if (name_val.m_Kind == VALUE_STRING)
                    obj_name = name_val.ToString();
            }
            trace << '{' << "\"object\":" << quote(obj_name)
                  << ",\"id\":" << builtin_json(self, "id")
                  << ",\"x\":" << builtin_json(self, "x")
                  << ",\"y\":" << builtin_json(self, "y")
                  << ",\"sprite_index\":" << builtin_json(self, "sprite_index")
                  << ",\"image_index\":" << builtin_json(self, "image_index")
                  << ",\"image_xscale\":" << builtin_json(self, "image_xscale")
                  << ",\"image_yscale\":" << builtin_json(self, "image_yscale")
                  << ",\"image_angle\":" << builtin_json(self, "image_angle")
                  << ",\"image_alpha\":" << builtin_json(self, "image_alpha")
                  << ",\"speed\":" << builtin_json(self, "speed")
                  << ",\"direction\":" << builtin_json(self, "direction")
                  << ",\"visible\":" << builtin_json(self, "visible")
                  << ",\"vars\":{";
            bool first_var = true;
            unsigned var_count = 0;
            api->EnumInstanceMembers(self->ToRValue(), [&](const char* member_name, RValue* member) {
                if (var_count++ >= 128) return true;
                if (member->m_Kind != VALUE_REAL && member->m_Kind != VALUE_INT32 &&
                    member->m_Kind != VALUE_INT64 && member->m_Kind != VALUE_BOOL &&
                    member->m_Kind != VALUE_STRING) return false;
                if (!first_var) trace << ',';
                first_var = false;
                trace << quote(member_name) << ':' << value_json(*member);
                return false;
            });
            trace << "}}";
        });
    }
    trace << "]}\n";
    trace.flush();
    ++gameplay_tick;
}

static void snapshot_catalog() {
    CInstance* globals = nullptr;
    if (AurieSuccess(api->GetGlobalInstance(&globals))) {
        trace << "{\"kind\":\"global_names\",\"names\":[";
        bool first = true;
        api->EnumInstanceMembers(globals->ToRValue(), [&](const char* name, RValue*) {
            if (!first) trace << ',';
            first = false;
            trace << quote(name);
            return false;
        });
        trace << "]}\n";
        for (const char* member_name : {"characterData", "attacksLibrary", "AttackModifiers",
                                        "stages", "characterList", "charSelected"}) {
            RValue* member = nullptr;
            auto status = api->GetInstanceMember(globals->ToRValue(), member_name, member);
            if (AurieSuccess(status)) {
                RValue selected = *member;
                if (std::string(member_name) == "characterData" &&
                    api->CallBuiltin("ds_exists", {*member, 1}).ToBoolean())
                    selected = api->CallBuiltin("ds_map_find_value", {*member, "suisei"});
                if (std::string(member_name) == "attacksLibrary" &&
                    api->CallBuiltin("ds_exists", {*member, 1}).ToBoolean())
                    selected = api->CallBuiltin("ds_map_find_value", {*member, "AxeSwing"});
                if (std::string(member_name) == "stages" &&
                    api->CallBuiltin("ds_exists", {*member, 1}).ToBoolean())
                    selected = api->CallBuiltin("ds_map_find_value", {*member, "STAGE 1"});
                trace << "{\"kind\":\"global_data\",\"name\":" << quote(member_name)
                      << ",\"state\":" << value_json(selected) << "}\n";
            }
        }
    }
    for (const char* name : {"obj_CharacterData", "obj_AttackController", "obj_StageManager",
                             "obj_PlayerManager", "obj_InputManager", "obj_GameManager"}) {
        api->InvokeWithObject(RValue(name), [&](CInstance* self, CInstance*) {
            trace << "{\"kind\":\"catalog_snapshot\",\"object\":" << quote(name)
                  << ",\"state\":{";
            bool first = true;
            api->EnumInstanceMembers(self->ToRValue(), [&](const char* member_name, RValue* member) {
                if (member->m_Kind != VALUE_REAL && member->m_Kind != VALUE_INT32 &&
                    member->m_Kind != VALUE_INT64 && member->m_Kind != VALUE_BOOL &&
                    member->m_Kind != VALUE_STRING) return false;
                if (!first) trace << ',';
                first = false;
                trace << quote(member_name) << ':' << value_json(*member);
                return false;
            });
            trace << "}}\n";
        });
    }
    trace.flush();
}

static void receive_commands() {
    auto path = trace_directory / "commands.txt";
    if (!fs::exists(path)) return;
    std::ifstream stream(path);
    std::string line;
    while (std::getline(stream, line)) {
        std::istringstream command(line);
        std::string verb;
        int key = 0;
        command >> verb;
        if ((verb == "press" || verb == "release") && command >> key && key >= 0 && key <= 255) {
            held_keys[key] = verb == "press";
            api->CallBuiltin(verb == "press" ? "keyboard_key_press" : "keyboard_key_release", {key});
        }
        else if (verb == "snapshot") {
            for (const char* name : {"obj_PlayerManager", "obj_InputManager",
                                     "obj_GameManager", "obj_MobManager"}) {
                api->InvokeWithObject(RValue(name), [&](CInstance* self, CInstance*) {
                    trace << "{\"kind\":\"catalog_snapshot\",\"object\":" << quote(name)
                          << ",\"state\":{";
                    bool first = true;
                    api->EnumInstanceMembers(self->ToRValue(), [&](const char* mn, RValue* m) {
                        if (m->m_Kind != VALUE_REAL && m->m_Kind != VALUE_INT32 &&
                            m->m_Kind != VALUE_INT64 && m->m_Kind != VALUE_BOOL &&
                            m->m_Kind != VALUE_STRING) return false;
                        if (!first) trace << ',';
                        first = false;
                        trace << quote(mn) << ':' << value_json(*m);
                        return false;
                    });
                    trace << "}}\n";
                });
            }
            trace.flush();
        }
        else if (verb == "screenshot") screenshot_requested = true;
        else if (verb == "call") {
            std::string object, method;
            command >> object >> method;
            const std::set<std::string> allowed = {"Confirmed", "SelectDown", "SelectUp",
                "SelectLeft", "SelectRight", "EnterKey", "ReturnMenu"};
            if (allowed.contains(method)) {
                api->InvokeWithObject(RValue(object.c_str()), [&](CInstance* self, CInstance*) {
                    RValue* function = nullptr;
                    if (AurieSuccess(api->GetInstanceMember(self->ToRValue(), method.c_str(), function))) {
                        auto args = api->CallBuiltin("array_create", {0});
                        api->CallBuiltin("method_call", {*function, args});
                    }
                });
            }
        }
        else if (verb == "set") {
            std::string object, member_name;
            double value;
            command >> object >> member_name >> value;
            api->InvokeWithObject(RValue(object.c_str()), [&](CInstance* self, CInstance*) {
                RValue* member = nullptr;
                if (AurieSuccess(api->GetInstanceMember(self->ToRValue(), member_name.c_str(), member))) {
                    *member = RValue(value);
                }
            });
        }
        else if (verb == "setglobal") {
            std::string member_name;
            double value;
            command >> member_name >> value;
            CInstance* globals = nullptr;
            if (AurieSuccess(api->GetGlobalInstance(&globals))) {
                RValue* member = nullptr;
                if (AurieSuccess(api->GetInstanceMember(globals->ToRValue(), member_name.c_str(), member)))
                    *member = RValue(value);
            }
        }
        else if (verb == "setglobalstr") {
            std::string member_name, value;
            command >> member_name;
            std::getline(command, value);
            if (!value.empty() && value[0] == ' ') value = value.substr(1);
            CInstance* globals = nullptr;
            if (AurieSuccess(api->GetGlobalInstance(&globals))) {
                RValue* member = nullptr;
                if (AurieSuccess(api->GetInstanceMember(globals->ToRValue(), member_name.c_str(), member)))
                    *member = RValue(value.c_str());
            }
        }
        else if (verb == "script") {
            std::string script_name;
            command >> script_name;
            api->CallGameScript(script_name, {});
        }
        else if (verb == "builtin") {
            std::string func_name;
            command >> func_name;
            std::vector<RValue> args;
            double arg;
            while (command >> arg) args.emplace_back(arg);
            api->CallBuiltin(func_name.c_str(), args);
        }
        trace << "{\"kind\":\"probe_command\",\"event_sequence\":" << event_sequence
              << ",\"command\":" << quote(line) << "}\n";
    }
    stream.close();
    fs::remove(path);
    trace.flush();
}

static void event_callback(FWCodeEvent& context) {
    auto* code = std::get<2>(context.Arguments());
    const char* raw_name = code ? code->GetName() : nullptr;
    std::string name = raw_name ? raw_name : "<unnamed>";
    ++event_sequence;
    if (name == "gml_Object_input_controller_object_Step_1") {
        receive_commands();
        for (int key = 0; key < 256; ++key)
            if (held_keys[key]) api->CallBuiltin("keyboard_key_press", {key});
    }
    if (event_names.insert(name).second) {
        trace << "{\"kind\":\"event_discovered\",\"event_sequence\":" << event_sequence
              << ",\"name\":" << quote(name) << "}\n";
        trace.flush();
    }
    // Preserve the original event and its result exactly once.
    // Let YYToolkit invoke ordinary events itself. Only sample after Player
    // Step when its post-event state is needed.
    if (name == "gml_Object_obj_Player_Step_0" && !context.CalledOriginal()) context.Call();
    if (!captured_catalog && presents >= 120 && name == "gml_Object_input_controller_object_Step_1") {
        captured_catalog = true;
        snapshot_catalog();
    }
    if (name == "gml_Object_obj_Player_Step_0") {
        auto* self = std::get<0>(context.Arguments());
        if (!in_gameplay) {
            in_gameplay = true;
            trace << "{\"kind\":\"gameplay_start\",\"event_sequence\":" << event_sequence
                  << ",\"tick_rate\":60}\n";
            trace.flush();
        }
        if (self) {
            trace << "{\"kind\":\"object_step\",\"event_sequence\":" << event_sequence
                  << ",\"event\":" << quote(name) << ",\"state\":"
                  << value_json(self->ToRValue()) << "}\n";
            trace.flush();
        }
        snapshot_world();
    }
}

static void frame_callback(FWFrame&) {
    ++presents;
    if (screenshot_requested) {
        screenshot_requested = false;
        auto filename = (trace_directory / "screen.png").string();
        api->CallBuiltin("screen_save", {filename.c_str()});
    }
    if (presents % 60 == 0) {
        trace << "{\"kind\":\"heartbeat\",\"presents\":" << presents
              << ",\"event_count\":" << event_sequence << "}\n";
        trace.flush();
    }
}

static void window_callback(FWWndProc& context) {
    UINT message = std::get<1>(context.Arguments());
    if (message == WM_CLOSE || message == WM_DESTROY || message == WM_QUIT) {
        trace << "{\"kind\":\"window_message\",\"message\":" << message << "}\n";
        trace.flush();
    }
}

EXPORTED AurieStatus ModuleInitialize(AurieModule* module, const fs::path&) {
    api = YYTK::GetInterface();
    if (!api) return AURIE_MODULE_DEPENDENCY_NOT_RESOLVED;
    char output[32768]{};
    DWORD size = GetEnvironmentVariableA("HOLOCURE_TRACE_DIR", output, sizeof(output));
    if (!size || size >= sizeof(output)) return AURIE_INVALID_PARAMETER;
    trace.open(fs::path(output) / "probe.jsonl", std::ios::out | std::ios::trunc);
    trace_directory = fs::path(output);
    if (!trace) return AURIE_ACCESS_DENIED;
    short major, minor, patch;
    api->QueryVersion(major, minor, patch);
    trace << "{\"kind\":\"probe_header\",\"schema_version\":1,\"yytk\":"
          << quote(std::to_string(major) + "." + std::to_string(minor) + "." + std::to_string(patch))
          << ",\"validation_status\":\"discovery_only\"}\n";
    trace.flush();
    char mode[8]{};
    bool passive = GetEnvironmentVariableA("HOLOCURE_PROBE_PASSIVE", mode, sizeof(mode)) != 0;
    auto status = passive ? AURIE_SUCCESS : api->CreateCallback(module, EVENT_OBJECT_CALL, reinterpret_cast<PVOID>(event_callback), 0);
    if (!AurieSuccess(status)) return status;
    status = api->CreateCallback(module, EVENT_FRAME, reinterpret_cast<PVOID>(frame_callback), 0);
    if (!AurieSuccess(status)) return status;
    status = api->CreateCallback(module, EVENT_WNDPROC, reinterpret_cast<PVOID>(window_callback), 0);
    // The framework requires initial window creation. Once initialized, hide
    // only this probe's windows so unattended research does not take focus.
    if (!GetEnvironmentVariableA("HOLOCURE_PROBE_VISIBLE", mode, sizeof(mode))) {
      EnumWindows([](HWND window, LPARAM) -> BOOL {
        DWORD owner = 0;
        GetWindowThreadProcessId(window, &owner);
        if (owner == GetCurrentProcessId()) ShowWindow(window, SW_HIDE);
        return TRUE;
    }, 0);
      if (GetConsoleWindow()) ShowWindow(GetConsoleWindow(), SW_HIDE);
    }
    return status;
}

EXPORTED AurieStatus ModuleUnload(AurieModule* module, const fs::path&) {
    if (api) {
        api->RemoveCallback(module, reinterpret_cast<PVOID>(event_callback));
        api->RemoveCallback(module, reinterpret_cast<PVOID>(frame_callback));
        api->RemoveCallback(module, reinterpret_cast<PVOID>(window_callback));
    }
    trace.close();
    return AURIE_SUCCESS;
}
