import QtQuick
import qs.Commons
import qs.Ui

// Nested pages use a breadcrumb-style return target above the page title.
// It reads as navigation, not as a competing primary action.
Column {
    id: root

    property string parentTitle: ""
    property string backAccessibleText: parentTitle
    property string title: ""
    property color foreground: Color.foreground
    property color dimForeground: foreground
    property color accent: Color.accent
    property string fontFamily: Style.font.family

    signal backRequested()

    width: parent ? parent.width : implicitWidth
    spacing: Style.spacing.xs

    BorderSurface {
        id: backLink

        width: Math.min(root.width, breadcrumb.implicitWidth + Style.spacing.md * 2)
        implicitHeight: Math.max(Style.space(30), breadcrumb.implicitHeight + Style.spacing.xs * 2)
        radius: Style.cornerRadius
        activeFocusOnTab: true

        readonly property bool hot: backMouse.containsMouse || activeFocus

        color: hot ? Style.hoverFillFor(root.accent, root.accent) : "transparent"
        borderSpec: activeFocus ? Border.controlSpec("focus", root.accent, root.accent) : Border.none()

        Behavior on color {
            ColorAnimation {
                duration: 60
            }
        }

        Row {
            id: breadcrumb
            anchors.centerIn: parent
            spacing: Style.spacing.xs

            PlainText {
                text: "←"
                color: backLink.hot ? root.accent : root.dimForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
            }

            PlainText {
                text: root.parentTitle
                color: backLink.hot ? root.accent : root.dimForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
            }
        }

        Keys.onReturnPressed: root.backRequested()
        Keys.onEnterPressed: root.backRequested()
        Keys.onSpacePressed: root.backRequested()

        Accessible.role: Accessible.Button
        Accessible.name: root.backAccessibleText

        MouseArea {
            id: backMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                backLink.forceActiveFocus();
                root.backRequested();
            }
        }
    }

    PlainText {
        width: parent.width
        text: root.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        elide: Text.ElideRight
    }
}
