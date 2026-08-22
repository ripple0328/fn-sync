import QtQuick
import qs.Commons
import qs.Ui

// Theme-native action for labels supplied by the NAS or controller. Unlike
// the shared Button component, this component explicitly renders plain text.
BorderSurface {
    id: root

    property string text: ""
    property bool selected: false
    property bool leftAlign: false
    property bool bordered: true
    property bool focusable: true
    property color foreground: Color.foreground
    property color accent: Color.accent
    property string fontFamily: Style.font.family

    signal clicked()

    implicitHeight: Math.max(Style.spacing.controlHeight, label.implicitHeight + Style.spacing.controlPaddingY * 2)
    radius: Style.cornerRadius
    activeFocusOnTab: enabled && focusable

    readonly property bool hot: pointer.containsMouse || activeFocus

    color: !enabled ? "transparent"
        : pointer.pressed ? Style.pressedFillFor(foreground, accent)
        : activeFocus ? Style.focusFillFor(foreground, accent)
        : hot ? Style.hoverFillFor(foreground, accent)
        : selected ? Style.selectedFillFor(foreground, accent)
        : "transparent"
    borderSpec: activeFocus
        ? Border.controlSpec("focus", foreground, accent)
        : hot
            ? Border.controlSpec("hover-cursor", foreground, accent)
            : selected
                ? Border.controlSpec("selected", foreground, accent)
                : bordered
                    ? Border.controlSpec("normal", foreground, accent)
                    : Border.none()

    PlainText {
        id: label
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.controlPaddingX
        anchors.rightMargin: Style.spacing.controlPaddingX
        text: root.text
        color: root.selected ? Style.selectedStateColor(root.foreground, root.accent) : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: root.selected
        horizontalAlignment: root.leftAlign ? Text.AlignLeft : Text.AlignHCenter
        elide: Text.ElideRight
    }

    Keys.onReturnPressed: if (enabled)
        root.clicked()
    Keys.onEnterPressed: if (enabled)
        root.clicked()
    Keys.onSpacePressed: if (enabled)
        root.clicked()

    Accessible.role: Accessible.Button
    Accessible.name: root.text

    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            root.forceActiveFocus();
            root.clicked();
        }
    }
}
