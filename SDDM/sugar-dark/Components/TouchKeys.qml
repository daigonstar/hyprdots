// An on-screen keyboard for the login screen, used when theme.conf.user sets TouchKeyboard=true (install/surface.sh does, on a
// Surface). Written here because Qt 5's own, which VirtualKeyboard.qml needs, is not in the Arch repos. It types into the
// username or password field that has the focus, and into nothing else. Log in with the form's own button.

import QtQuick 2.11
import QtQuick.Window 2.2

Rectangle {
    id: keys

    // What Main.qml expects of a keyboard: it shows and hides this itself
    property bool activated: false
    property bool active: false

    property int page: 0  // 0 lower case, 1 upper case, 2 symbols, 3 more symbols
    readonly property var layout: [
        ["q w e r t y u i o p", "a s d f g h j k l", "z x c v b n m"],
        ["Q W E R T Y U I O P", "A S D F G H J K L", "Z X C V B N M"],
        ["1 2 3 4 5 6 7 8 9 0", "! \" £ $ % ^ & * ( )", "- _ = + @ # ?"],
        ["~ ` | \\ / [ ] { } €", "< > : ; ' , ¬ ¦ ° §", "¡ ¿ « » × ÷ ·"]
    ]
    readonly property int keySize: Math.min(64, (width - 80) / 10)

    implicitHeight: column.implicitHeight + 24
    color: "#d0000000"

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

                Key {
                    visible: rowIndex == 2
                    label: keys.page >= 2 ? (keys.page == 2 ? "More" : "Back") : "Shift"
                    wide: true
                    onPressed: keys.page = [1, 0, 3, 2][keys.page]
                }
                Repeater {
                    model: keys.layout[keys.page][rowIndex].split(" ")
                    Key {
                        label: modelData
                        onPressed: keys.type(modelData)
                    }
                }
                Key {
                    visible: rowIndex == 2
                    label: "⌫"
                    wide: true
                    onPressed: keys.erase()
                }
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 6
            Key {
                label: keys.page >= 2 ? "abc" : "123"
                wide: true
                onPressed: keys.page = keys.page >= 2 ? 0 : 2
            }
            Key {
                label: ""
                width: keys.keySize * 5
                onPressed: keys.type(" ")
            }
            Key {
                label: "Hide"
                wide: true
                onPressed: keys.parent.switchState()
            }
        }
    }
}
