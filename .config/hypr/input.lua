hl.config({
    input = {
        kb_layout = "gb",
        kb_variant = "",
        kb_model = "",
        kb_options = "",
        kb_rules = "",
        follow_mouse = 1,
        sensitivity = 0,
        touchpad = {
            natural_scroll = false,
        },
    },
})

-- Touchpad: three fingers across for workspaces, four up for the overview. The touchscreen's are in tray/touch_gestures.py.
hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
hl.gesture({ fingers = 4, direction = "up", action = function()
    hl.exec_cmd("pkill -HUP -f '[h]ypr/tray/quick_tray'")
end })

hl.device({
    name = "epic-mouse-v1",
    sensitivity = 0,
})
