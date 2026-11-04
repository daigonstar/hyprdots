// An on-screen keyboard for the login screen, used when theme.conf.user sets TouchKeyboard=true (install/surface.sh does, on a
// Surface). Written here because Qt 5's own, which VirtualKeyboard.qml needs, is not in the Arch repos. It types into the
// username or password field that has the focus, and into nothing else. The same layout as the desktop's and the lock screen's:
// install/tests/test_keyboards.py checks they agree. Split in two for the thumbs on a wide screen.

import QtQuick 2.11
import QtQuick.Window 2.2

Rectangle {
    id: keys

    // What Main.qml expects of a keyboard: it shows and hides this itself
    property bool activated: false
    property bool active: false

    property int page: 0  // 0 lower case, 1 upper case, 2 numbers, 3 symbols
    readonly property var layout: [
        [["q w e r t", "a s d f g", "z x c v"], ["y u i o p", "h j k l '", "b n m ,"]],
        [["Q W E R T", "A S D F G", "Z X C V"], ["Y U I O P", "H J K L '", "B N M ,"]],
        [["1 2 3 4 5", "@ # $ % &", ", \" ' :"], ["6 7 8 9 0", "- _ + ( )", "; ! ? /"]],
        [["~ ` | · √", "© ® £ € ¥", "\\ / < >"], ["π τ ÷ × ¶", "^ ° * { }", "= [ ] ¬"]]
    ]
    readonly property bool split: width > height * 1.2 && width > keySize * 14
    readonly property int keySize: Math.min(78, (width - 84) / 10)  // the size of the desktop keyboard's, on a screen wide enough
    readonly property int gap: split ? Math.max(0, width - keySize * 12.4 - 60) : 6

    implicitHeight: column.implicitHeight + 24
    color: "#1b1d1d"

    function field() {
        var item = Window.activeFocusItem
        return item && item.insert ? item : null
    }

    function type(text) {
        var target = field()
        if (target)
            target.insert(target.cursorPosition, text)
        if (page == 1)
            page = 0  // Shift lasts for one letter
    }

    function erase() {
        var target = field()
        if (target && target.cursorPosition > 0)
            target.remove(target.cursorPosition - 1, target.cursorPosition)
    }

    Column {
        id: column
        anchors.centerIn: parent
        spacing: 6

        Repeater {
            model: 3
            Row {
                readonly property int rowIndex: index
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 6

                Row {
                    spacing: 6
                    Key {
                        visible: rowIndex == 2
                        label: keys.page >= 2 ? (keys.page == 2 ? "*/=" : "123") : "⇧"
                        wide: true
                        action: true
                        onPressed: keys.page = [1, 0, 3, 2][keys.page]
                    }
                    Repeater {
                        model: keys.layout[keys.page][0][rowIndex].split(" ")
                        Key {
                            label: modelData
                            onPressed: keys.type(modelData)
                        }
                    }
                }
                Item { width: keys.gap - 12; height: 1 }
                Row {
                    spacing: 6
                    Repeater {
                        model: keys.layout[keys.page][1][rowIndex].split(" ")
                        Key {
                            label: modelData
                            onPressed: keys.type(modelData)
                        }
                    }
                    Key {
                        visible: rowIndex == 2
                        label: "⌫"
                        wide: true
                        action: true
                        onPressed: keys.erase()
                    }
                }
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 6
            Key {
                label: keys.page >= 2 ? "ABC" : "123"
                wide: true
                action: true
                onPressed: keys.page = keys.page >= 2 ? 0 : 2
            }
            Key {
                label: "Hide"
                wide: true
                action: true
                onPressed: keys.parent.switchState()
            }
            Key {
                visible: keys.split
                label: ""
                width: keys.keySize * 2.65  // so that this half ends level with the rows above
                onPressed: keys.type(" ")
            }
            Item { visible: keys.split; width: keys.gap - 12; height: 1 }
            Key {
                label: ""
                width: keys.keySize * (keys.split ? 3.15 : 3.5)
                onPressed: keys.type(" ")
            }
            Key {
                label: "."
                onPressed: keys.type(".")
            }
            Key {
                label: "Log in"
                wide: true
                accent: true
                onPressed: {
                    var target = keys.field()
                    if (target)
                        target.accepted()
                }
            }
        }
    }
}
