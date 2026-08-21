import QtQuick
import qs.Commons
import qs.Ui

// Nested-page navigation follows Omarchy's compact panel-header pattern:
// one quiet icon action and one page title on the same visual line.
Row {
    id: root

    property string backText: ""
    property string title: ""
    property color foreground: Color.foreground
    property color accent: Color.accent
    property string fontFamily: Style.font.family

    signal backRequested()

    width: parent ? parent.width : implicitWidth
    spacing: Style.spacing.sm

    PanelActionButton {
        id: backButton
        anchors.verticalCenter: parent.verticalCenter
        iconText: "󰁍"
        tooltipText: root.backText
        foreground: root.foreground
        hoverColor: root.accent
        fontFamily: root.fontFamily
        fontSize: Style.font.icon
        size: Math.max(Style.space(30), Style.font.icon + Style.spacing.sm * 2)
        focusable: true
        bordered: false

        Accessible.role: Accessible.Button
        Accessible.name: root.backText

        onClicked: root.backRequested()
    }

    Text {
        width: Math.max(0, parent.width - backButton.width - parent.spacing)
        anchors.verticalCenter: parent.verticalCenter
        text: root.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        elide: Text.ElideRight
    }
}
