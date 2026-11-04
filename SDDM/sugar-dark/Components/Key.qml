// One key of TouchKeys.qml. A MouseArea, not a Button, so that the field being typed into keeps the focus.

import QtQuick 2.11

Rectangle {
    id: key

    property string label
    property bool wide: false
    signal pressed

    width: keys.keySize * (wide ? 1.5 : 1)
    height: keys.keySize
    radius: 8
    color: area.pressed ? "#66ffffff" : "#26ffffff"

    Text {
        anchors.centerIn: parent
        text: key.label
        color: "white"
        font.pixelSize: key.height * 0.36
    }

    MouseArea {
        id: area
        anchors.fill: parent
        onClicked: key.pressed()
    }
}
