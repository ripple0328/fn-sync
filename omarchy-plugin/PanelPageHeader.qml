import QtQuick
import qs.Commons
import qs.Ui

// Nested-page navigation that follows Omarchy's quiet submenu pattern:
// a compact, contextual back link followed by the current page title.
Column {
    id: root

    property string backText: ""
    property string title: ""
    property color foreground: Color.foreground
    property color accent: Color.accent
    property string fontFamily: Style.font.family

    signal backRequested()

    readonly property color dim: Qt.darker(foreground, 1.4)

    width: parent ? parent.width : implicitWidth
    spacing: Style.space(4)

    Item {
        id: backLink

        readonly property bool hot: backMouse.containsMouse || activeFocus

        width: Math.min(parent.width, Math.max(Style.space(44), backContent.implicitWidth + Style.space(16)))
        implicitHeight: Style.space(30)
        activeFocusOnTab: true

        Accessible.role: Accessible.Button
        Accessible.name: root.backText

        Keys.onReturnPressed: root.backRequested()
        Keys.onEnterPressed: root.backRequested()
        Keys.onSpacePressed: root.backRequested()

        BorderSurface {
            anchors.fill: parent
            radius: Style.cornerRadius
            color: backLink.hot ? Style.hoverFillFor(root.foreground, root.accent) : "transparent"
            borderSpec: backLink.activeFocus
                ? Border.controlSpec("focus", root.foreground, root.accent)
                : Border.none()

            Behavior on color {
                ColorAnimation { duration: 60 }
            }
        }

        Row {
            id: backContent
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(5)

            Text {
                width: Style.space(12)
                horizontalAlignment: Text.AlignHCenter
                text: "\u2039"
                color: backLink.hot ? root.accent : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
            }

            Text {
                text: root.backText
                color: backLink.hot ? root.foreground : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: backLink.hot
                elide: Text.ElideRight
            }
        }

        MouseArea {
            id: backMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                backLink.forceActiveFocus()
                root.backRequested()
            }
        }
    }

    Text {
        width: parent.width
        text: root.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        elide: Text.ElideRight
    }
}
