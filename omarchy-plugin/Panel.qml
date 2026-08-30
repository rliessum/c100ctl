import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
    id: root
    moduleName: "io.github.rliessum.c100ctl"
    manageIpc: false

    property var anchorItem: null
    property var hostWidget: null
    property var profiles: []
    property string activeProfile: ""

    function open() {
        root.controller.show()
    }

    function close() {
        root.controller.hide()
    }

    function toggle() {
        if (root.opened) {
            root.close()
        } else {
            root.open()
        }
    }

    function switchPanel(direction) {
        if (root.bar && typeof root.bar.switchPanelFrom === "function")
            return root.bar.switchPanelFrom(root.hostWidget || root, direction)
        return false
    }

    function selectProfile(name) {
        switchProcess.exec({ command: [findC100ctl(), "profile", "--use", name] })
    }

    function openConfigurator() {
        root.close()
        configuratorProcess.running = true
    }

    function findC100ctl() {
        if (whichProcess.foundPath !== "") return whichProcess.foundPath
        return "c100ctl"
    }

    function findUwsm() {
        if (whichUwsmProcess.foundPath !== "") return whichUwsmProcess.foundPath
        return ""
    }

    Component.onCompleted: {
        whichProcess.running = true
        whichUwsmProcess.running = true
    }

    Process {
        id: whichProcess
        property string foundPath: ""
        command: ["which", "c100ctl"]
        running: false
        stdout: StdioCollector {
            onStreamFinished: {
                var path = this.text.trim()
                if (path !== "") {
                    whichProcess.foundPath = path
                }
            }
        }
    }

    Process {
        id: whichUwsmProcess
        property string foundPath: ""
        command: ["which", "uwsm"]
        running: false
        stdout: StdioCollector {
            onStreamFinished: {
                var path = this.text.trim()
                if (path !== "") {
                    whichUwsmProcess.foundPath = path
                }
            }
        }
    }

    Process {
        id: switchProcess
        running: false
        onRunningChanged: {
            if (!running) {
                if (root.hostWidget && typeof root.hostWidget.refresh === "function") {
                    root.hostWidget.refresh()
                }
                root.close()
            }
        }
    }

    Process {
        id: configuratorProcess
        command: root.findUwsm() !== ""
            ? [root.findUwsm(), "app", "c100ctl.desktop"]
            : [root.findC100ctl()]
        running: false
    }

    KeyboardPanel {
        id: panel
        anchorItem: root.anchorItem
        owner: root.hostWidget || root
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        contentWidth: panel.fittedContentWidth(Style.space(200))
        contentHeight: panel.fittedContentHeight(content.implicitHeight)

        PanelKeyCatcher {
            id: keyCatcher
            anchors.fill: parent
            onCloseRequested: root.close()
            onTabRequested: function(direction) { root.switchPanel(direction) }

            Column {
                id: content
                width: parent.width
                spacing: Style.space(4)

                Text {
                    width: parent.width
                    text: "C100 Profiles"
                    color: root.barForeground
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    bottomPadding: Style.space(8)
                }

                Repeater {
                    model: root.profiles

                    Rectangle {
                        width: parent.width
                        height: profileRow.implicitHeight + Style.space(12)
                        color: profileArea.containsMouse
                            ? Qt.rgba(root.barForeground.r, root.barForeground.g, root.barForeground.b, 0.1)
                            : "transparent"
                        radius: Style.space(4)

                        Row {
                            id: profileRow
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: Style.space(8)
                            spacing: Style.space(8)

                            Text {
                                text: modelData === root.activeProfile ? "●" : ""
                                color: root.barForeground
                                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                                font.pixelSize: Style.font.body
                                width: Style.space(16)
                            }

                            Text {
                                text: modelData
                                color: root.barForeground
                                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                                font.pixelSize: Style.font.body
                                font.bold: modelData === root.activeProfile
                            }
                        }

                        MouseArea {
                            id: profileArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.selectProfile(modelData)
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: root.profiles.length === 0 ? "No profiles found" : ""
                    color: Qt.rgba(root.barForeground.r, root.barForeground.g, root.barForeground.b, 0.6)
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.body
                    font.italic: true
                    horizontalAlignment: Text.AlignHCenter
                    visible: root.profiles.length === 0
                }

                Item {
                    width: parent.width
                    height: Style.space(8)
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Qt.rgba(root.barForeground.r, root.barForeground.g, root.barForeground.b, 0.2)
                }

                Item {
                    width: parent.width
                    height: Style.space(4)
                }

                Rectangle {
                    width: parent.width
                    height: configRow.implicitHeight + Style.space(12)
                    color: configArea.containsMouse
                        ? Qt.rgba(root.barForeground.r, root.barForeground.g, root.barForeground.b, 0.1)
                        : "transparent"
                    radius: Style.space(4)

                    Row {
                        id: configRow
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: Style.space(8)

                        Text {
                            text: "⚙"
                            color: root.barForeground
                            font.pixelSize: Style.font.body
                        }

                        Text {
                            text: "Configure pad"
                            color: root.barForeground
                            font.family: root.bar ? root.bar.fontFamily : Style.font.family
                            font.pixelSize: Style.font.body
                        }
                    }

                    MouseArea {
                        id: configArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: root.openConfigurator()
                    }
                }
            }
        }
    }
}
