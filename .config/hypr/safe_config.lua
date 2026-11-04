-- Safe mode: a Lua file that fails to load is replaced by its last copy that worked, so one mistake cannot leave a desktop
-- with no keybinds. Copies are taken after every clean load, and only the failed file falls back. Keep this file simple.
local M = {}
local STATE = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")) .. "/hyprdots/last_good/"
local real_require = require
local loaded, problems = {}, {}

local function read(path)
    local file = io.open(path, "rb")
    if not file then return nil end
    local text = file:read("a")
    file:close()
    return text
end

-- Every require goes through here, so files that other files load are covered too (user_overrides, theme, window_rules...).
-- Hyprland's require does not raise: it adds to `hyprctl configerrors` and returns a stand-in table without the second
-- value (where the file was) that a real load returns.
function require(name)
    if package.loaded[name] ~= nil then return package.loaded[name] end
    local file = package.searchpath(name, package.path)
    local ok, result, where = pcall(real_require, name)
    if not file then  -- an optional file that is not there is not a problem
        if ok then return result end
        error(result, 2)
    end
    if ok and where ~= nil then
        loaded[name] = file
        return result
    end
    problems[#problems + 1] = name
    if name == "keybinds" then hl.unbind("all") end  -- it may have got part of the way
    local copy = loadfile(STATE .. name .. ".lua")
    local good, value = pcall(copy or error, "no saved copy of " .. name)
    if not good then error(name .. " failed, and so did its saved copy", 2) end
    package.loaded[name] = value == nil and true or value
    return package.loaded[name]
end

-- Only enough to get to a terminal and fix it, if the keybinds failed and there is no saved copy to use
local function emergency_keys()
    hl.bind("SUPER + RETURN", hl.dsp.exec_cmd("ghostty || kitty || foot || alacritty || xterm"))
    hl.bind("SUPER + END", hl.dsp.exit())
end

function M.load(name)
    local ok = pcall(require, name)
    if not ok and name == "keybinds" then emergency_keys() end
end

local function save()
    os.execute("mkdir -p '" .. STATE .. "'")
    for name, file in pairs(loaded) do
        local text, target = read(file), STATE .. name .. ".lua"
        if text and text ~= read(target) then
            local out = io.open(target .. ".new", "wb")
            if out then
                out:write(text)
                out:close()
                os.rename(target .. ".new", target)
            end
        end
    end
end

-- Last line of hyprland.lua. A clean load is saved; otherwise you are told. `hyprctl configerrors` has the details.
function M.finish()
    if #problems == 0 then
        hl.on("hyprland.start", save)
        hl.on("config.reloaded", save)
        return
    end
    hl.notification.create({
        text = "Safe mode: " .. table.concat(problems, ", ") .. " failed to load, so the last working copy is in use. Fix it and save.",
        timeout = 15000,
        color = "rgb(ff5555)",
    })
end

return M
