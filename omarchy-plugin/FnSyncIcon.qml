import QtQuick
import QtQuick.Effects
import Quickshell

// Exact Feiniu Sync mark extracted from the official desktop-client artwork.
// It is used as an alpha mask so Omarchy controls its color like every other
// symbolic status icon.
Item {
    id: root

    property real iconSize: 13
    property color color: "white"

    width: iconSize * 37 / 29
    height: iconSize
    implicitWidth: width
    implicitHeight: height

    Behavior on color {
        ColorAnimation {
            duration: 160
        }
    }

    Image {
        id: mark
        anchors.fill: parent
        source: Qt.resolvedUrl("assets/fn-sync-symbolic.png")
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        sourceSize.width: Math.round(width * Screen.devicePixelRatio)
        sourceSize.height: Math.round(height * Screen.devicePixelRatio)
        visible: false
        layer.enabled: true
    }

    MultiEffect {
        anchors.fill: mark
        source: mark
        colorization: 1.0
        colorizationColor: root.color
    }
}
