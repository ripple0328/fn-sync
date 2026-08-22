import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// Single-select dropdown for controller-provided labels. Every visible value
// is rendered by PlainText so NAS or task names can never become rich text.
Item {
    id: root

    property string label: ""
    property string value: ""
    property var options: []
    property color foreground: Color.popups.text
    property color background: Color.popups.background
    property color popupBorder: Color.popups.border
    property color accent: Color.accent
    property string fontFamily: Style.font.family
    property int rowHeight: Style.spacing.controlHeight
    property int popupRowHeight: Style.spacing.popupRowHeight

    readonly property bool popupOpen: popup.opened
    readonly property var popupBorderSpec: Border.localOrSurfaceSpec("popups", "border", popupBorder, Color.popups.border, Style.normalBorderWidth)

    signal changed(string value)

    function optionValue(option) {
        return option && typeof option === "object" ? String(option.value) : String(option);
    }

    function optionLabel(option) {
        return option && typeof option === "object" ? String(option.label) : String(option);
    }

    function currentLabel() {
        for (var i = 0; i < options.length; i++) {
            if (optionValue(options[i]) === value)
                return optionLabel(options[i]);
        }
        return value;
    }

    function close() {
        popup.close();
    }

    implicitWidth: Style.spacing.dropdownWidth
    implicitHeight: rowHeight + Style.spacing.huge

    Column {
        anchors.fill: parent
        spacing: Style.spacing.labelGap

        PlainText {
            text: root.label
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
        }

        BorderSurface {
            id: trigger
            width: parent.width
            height: root.rowHeight
            radius: Style.cornerRadius
            activeFocusOnTab: true

            readonly property bool hot: triggerHover.hovered || activeFocus

            color: Style.controlFill(activeFocus, hot, root.foreground, root.accent)
            borderSpec: Border.controlSpec(activeFocus ? "focus" : hot ? "hover-cursor" : "normal", root.foreground, root.accent)

            PlainText {
                anchors.left: parent.left
                anchors.right: chevron.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.spacing.controlPaddingX
                anchors.rightMargin: Style.spacing.md
                text: root.currentLabel()
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                elide: Text.ElideRight
            }

            PlainText {
                id: chevron
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: Style.spacing.controlGap
                text: "󰅀"
                color: Qt.darker(root.foreground, 1.2)
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
            }

            HoverHandler {
                id: triggerHover
            }

            Keys.onPressed: function (event) {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space || event.key === Qt.Key_Down) {
                    popup.opened ? popup.close() : popup.open();
                    event.accepted = true;
                } else if (event.key === Qt.Key_Escape && popup.opened) {
                    popup.close();
                    event.accepted = true;
                }
            }

            Accessible.role: Accessible.ComboBox
            Accessible.name: root.label

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    trigger.forceActiveFocus();
                    popup.opened ? popup.close() : popup.open();
                }
            }

            Popup {
                id: popup
                x: 0
                y: trigger.height + Style.spacing.xxs
                width: trigger.width
                implicitHeight: Math.min(optionList.contentHeight + Style.spacing.xxs * 2, root.popupRowHeight * 8 + Style.spacing.xxs * 2)
                padding: Style.spacing.hairline
                focus: true

                background: BorderSurface {
                    color: root.background
                    borderSpec: root.popupBorderSpec
                    radius: Style.cornerRadius
                }

                onOpened: {
                    optionList.currentIndex = optionList.indexOfValue(root.value);
                    optionList.forceActiveFocus();
                }

                contentItem: ListView {
                    id: optionList
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: root.options
                    currentIndex: -1

                    function indexOfValue(wanted) {
                        for (var i = 0; i < root.options.length; i++) {
                            if (root.optionValue(root.options[i]) === wanted)
                                return i;
                        }
                        return root.options.length > 0 ? 0 : -1;
                    }

                    function selectCurrent() {
                        if (currentIndex < 0 || currentIndex >= root.options.length)
                            return;
                        var selectedValue = root.optionValue(root.options[currentIndex]);
                        root.value = selectedValue;
                        root.changed(selectedValue);
                        popup.close();
                    }

                    Keys.onPressed: function (event) {
                        if (event.key === Qt.Key_Escape) {
                            popup.close();
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Down || event.text === "j") {
                            currentIndex = Math.min(root.options.length - 1, currentIndex + 1);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Up || event.text === "k") {
                            currentIndex = Math.max(0, currentIndex - 1);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            selectCurrent();
                            event.accepted = true;
                        }
                    }

                    delegate: BorderSurface {
                        required property var modelData
                        required property int index
                        width: optionList.width
                        height: root.popupRowHeight
                        radius: Style.cornerRadius
                        color: index === optionList.currentIndex ? Style.hoverFillFor(root.foreground, root.accent) : "transparent"
                        borderSpec: Border.none()

                        PlainText {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: Style.spacing.controlPaddingX
                            anchors.rightMargin: Style.spacing.controlPaddingX
                            text: root.optionLabel(modelData)
                            color: index === optionList.currentIndex ? Style.hoverStateColor(root.foreground, root.accent) : root.foreground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.body
                            elide: Text.ElideRight
                        }

                        HoverHandler {
                            onHoveredChanged: if (hovered)
                                optionList.currentIndex = parent.index
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                optionList.currentIndex = parent.index;
                                optionList.selectCurrent();
                            }
                        }
                    }
                }
            }
        }
    }
}
