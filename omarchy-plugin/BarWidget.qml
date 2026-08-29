import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
    id: root
    moduleName: "io.github.rliessum.c100ctl"

    readonly property bool opened: panelLoader.item
        ? panelLoader.item.opened === true
        : false
    readonly property bool popoutSwitchClosing: panelLoader.item
        ? panelLoader.item.popoutSwitchClosing === true
        : false

    property string activeProfile: ""
    property var profiles: []
    property int refreshIntervalSec: 5

    function open() {
        if (panelLoader.item) panelLoader.item.open()
    }

    function close() {
        if (panelLoader.item) panelLoader.item.close()
    }

    function toggle() {
        if (panelLoader.item) panelLoader.item.toggle()
    }

    function closeForPopoutSwitch() {
        if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
    }

    function injectPanel() {
        if (!panelLoader.item) return
        panelLoader.item.bar = root.bar
        panelLoader.item.anchorItem = button
        panelLoader.item.hostWidget = root
        panelLoader.item.profiles = Qt.binding(function() { return root.profiles })
        panelLoader.item.activeProfile = Qt.binding(function() { return root.activeProfile })
    }

    function refresh() {
        profileProcess.running = true
    }

    function findC100ctl() {
        if (whichProcess.foundPath !== "") return whichProcess.foundPath
        return "c100ctl"
    }

    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    onBarChanged: injectPanel()

    Component.onCompleted: {
        whichProcess.running = true
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
                root.refresh()
            }
        }
    }

    Process {
        id: profileProcess
        command: [root.findC100ctl(), "profile", "--json"]
        running: false
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var data = JSON.parse(this.text)
                    if (data.ok) {
                        root.activeProfile = data.active || ""
                        root.profiles = data.profiles || []
                    }
                } catch (e) {
                    console.warn("c100ctl profile --json parse error:", e)
                }
            }
        }
    }

    Timer {
        interval: root.refreshIntervalSec * 1000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    Loader {
        id: panelLoader
        active: true
        source: Qt.resolvedUrl("Panel.qml")
        visible: false
        onLoaded: {
            root.injectPanel()
            Qt.callLater(root.injectPanel)
        }
    }

    WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: root.activeProfile || "C100"
        tooltipText: "Switch C100 profile"
        onPressed: function(buttonCode) {
            if (buttonCode === Qt.LeftButton) root.toggle()
        }
    }
}
