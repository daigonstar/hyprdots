// One key of TouchKeys.qml. A MouseArea, not a Button, so that the field being typed into keeps the focus.

import QtQuick 2.11

Rectangle {
    id: key

    property string label
    property bool wide: false
    property bool action: false  // keys that do something rather than type
    property bool accent: false
    signal pressed

    width: keys.keySize * (wide ? 1.5 : 1)
    height: keys.keySize * 0.85
    radius: 8
    color: area.pressed ? "#5c6060" : accent ? "#70CFB3" : action ? "#3a3e3e" : "#292c2c"

    Text {
        anchors.centerIn: parent
        text: key.label
        color: key.accent ? "black" : "#E4F5F6"
        font.pixelSize: key.height * 0.4
    }

    MouseArea {
        id: area
        anchors.fill: parent
        onClicked: key.pressed()
    }
}
