import QtQuick 2.15
import QtQuick.Controls 2.15

Rectangle {
    id: root
    color: "#07080b"

    // SDDM passes the chosen session by index. This has to be a real property:
    // the previous version assigned to a bare `sessionIndex`, which is an error
    // in QML and left the login call referencing an undefined value.
    property int sessionIndex: sessionSelect.currentIndex

    function attemptLogin() {
        errorText.text = ""
        sddm.login(userField.text, passField.text, root.sessionIndex)
    }

    function updateClock() {
        var now = new Date()
        timeText.text = Qt.formatTime(now, "hh:mm")
        // "dddd, MMMM d" gives "sábado, agosto 1" once the locale is pt_BR:
        // the day and month names translate but the order does not, and no
        // one writes a date that way in Portuguese. Spelled out explicitly,
        // with the weekday capitalised the way a sentence would be.
        var day = Qt.formatDate(now, "dddd")
        dateText.text = day.charAt(0).toUpperCase() + day.slice(1)
                      + Qt.formatDate(now, ", d 'de' MMMM")
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            errorText.text = capsWarning.visible
                ? "Usuário ou senha incorretos — o Caps Lock está ligado"
                : "Usuário ou senha incorretos"
            passField.text = ""
            passField.forceActiveFocus()
        }
    }

    Image {
        anchors.fill: parent
        source: "background.png"
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
    }

    Rectangle {
        anchors.fill: parent
        color: "#07080b"
        opacity: 0.55
    }

    // ── Login card ───────────────────────────────────────────────────────────
    Rectangle {
        id: card
        anchors.centerIn: parent
        width: 360
        // Sized to its contents rather than pinned at 390. The Caps Lock
        // warning and the failure message both appear and disappear, and a
        // fixed height meant whichever one showed last pushed the login button
        // towards the card's edge.
        height: form.implicitHeight + 56
        radius: 16
        color: "#07080b"
        border.color: "#0d0f14"
        border.width: 1

        Column {
            id: form
            anchors.centerIn: parent
            spacing: 16
            width: parent.width - 60

            Text {
                text: "STYLUS"
                font.pixelSize: 38
                font.bold: true
                font.family: "JetBrainsMono Nerd Font"
                color: "#5bcefa"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                text: "IFMS · Campus Dourados"
                font.pixelSize: 11
                color: "#7e899c"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            // The accounts on this machine, as things to click.
            //
            // Typing your username is a small barrier and an entirely
            // unnecessary one: the greeter already knows who exists. A student
            // sitting down at a lab machine should be able to point at their
            // name. The text field is still underneath for anything the list
            // does not cover - a domain account, or a machine with more users
            // than fit - so nothing is lost.
            Flow {
                id: userList
                width: parent.width
                spacing: 6
                visible: userModel.count > 0 && userModel.count <= 6

                Repeater {
                    model: userModel
                    delegate: Rectangle {
                        property bool current: userField.text === model.name
                        radius: 8
                        height: 34
                        width: Math.max(72, nameText.implicitWidth + 26)
                        color: current ? "#5bcefa"
                             : (userMouse.containsMouse ? "#141820" : "#0d0f14")
                        border.color: current ? "#5bcefa" : "#141820"
                        border.width: 1

                        Text {
                            id: nameText
                            anchors.centerIn: parent
                            text: model.realName !== "" ? model.realName : model.name
                            color: parent.current ? "#07080b" : "#e2e7f0"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }

                        MouseArea {
                            id: userMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                userField.text = model.name
                                passField.text = ""
                                passField.forceActiveFocus()
                            }
                        }
                    }
                }
            }

            TextField {
                id: userField
                width: parent.width
                height: 42
                placeholderText: "Usuário"
                text: userModel.lastUser
                font.pixelSize: 13
                color: "#e2e7f0"
                leftPadding: 14
                background: Rectangle {
                    color: "#0d0f14"
                    radius: 8
                    border.color: userField.activeFocus ? "#5bcefa" : "#141820"
                    border.width: 1
                }
                KeyNavigation.tab: passField
                Keys.onReturnPressed: passField.forceActiveFocus()
            }

            TextField {
                id: passField
                width: parent.width
                height: 42
                placeholderText: "Senha"
                echoMode: revealPass.checked ? TextInput.Normal : TextInput.Password
                font.pixelSize: 13
                color: "#e2e7f0"
                leftPadding: 14
                rightPadding: 44
                background: Rectangle {
                    color: "#0d0f14"
                    radius: 8
                    border.color: passField.activeFocus ? "#5bcefa" : "#141820"
                    border.width: 1
                }
                Keys.onReturnPressed: root.attemptLogin()

                // Show the password. On a keyboard whose layout may not be
                // what the student expects - and this image ships ABNT2, so
                // symbols land somewhere else than on the machine they last
                // used - a hidden field gives no way to tell a typo from a
                // wrong layout.
                Text {
                    id: revealPass
                    property bool checked: false
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    text: revealPass.checked ? "ocultar" : "mostrar"
                    font.pixelSize: 11
                    color: revealMouse.containsMouse ? "#5bcefa" : "#7e899c"
                    MouseArea {
                        id: revealMouse
                        anchors.fill: parent
                        anchors.margins: -6
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: revealPass.checked = !revealPass.checked
                    }
                }
            }

            // Caps Lock is the single most common reason a password that is
            // being typed correctly is rejected, and nothing on the old screen
            // said a word about it.
            Text {
                id: capsWarning
                width: parent.width
                visible: keyboard.capsLock
                text: "Caps Lock está ligado"
                color: "#f9e2af"
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
            }

            Text {
                id: errorText
                width: parent.width
                text: ""
                // A Text with no text is still a line tall, so without this the
                // card carried a permanent blank gap where an error might one
                // day go.
                visible: text !== ""
                color: "#f38ba8"
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            Rectangle {
                id: loginBtn
                width: parent.width
                height: 42
                radius: 8
                color: loginMouse.pressed ? "#00c47d" : "#5bcefa"

                Text {
                    anchors.centerIn: parent
                    text: "Entrar"
                    font.pixelSize: 13
                    font.bold: true
                    color: "#07080b"
                }

                MouseArea {
                    id: loginMouse
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.attemptLogin()
                }
            }
        }
    }

    // ── Clock ────────────────────────────────────────────────────────────────
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 32
        spacing: 4

        Text {
            id: timeText
            anchors.horizontalCenter: parent.horizontalCenter
            font.pixelSize: 42
            font.bold: true
            font.family: "JetBrainsMono Nerd Font"
            color: "#e2e7f0"
        }

        Text {
            id: dateText
            anchors.horizontalCenter: parent.horizontalCenter
            font.pixelSize: 14
            color: "#7e899c"
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.updateClock()
    }

    // ── Keyboard layout ──────────────────────────────────────────────────────
    //  This image ships ABNT2. Someone arriving from a machine set to US will
    //  find ? / ; and the accent keys in different places, which at a password
    //  field looks exactly like the password being wrong. Saying which layout
    //  is active costs one label.
    Text {
        anchors.top: parent.top
        anchors.right: sessionSelect.left
        anchors.rightMargin: 12
        anchors.topMargin: 16
        height: 32
        verticalAlignment: Text.AlignVCenter
        text: keyboard.layouts.length > 0
              ? keyboard.layouts[keyboard.currentLayout].shortName.toUpperCase()
              : ""
        color: "#7e899c"
        font.pixelSize: 11
    }

    // ── Session picker ───────────────────────────────────────────────────────
    ComboBox {
        id: sessionSelect
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 16
        width: 160
        height: 32
        model: sessionModel
        textRole: "name"
        currentIndex: sessionModel.lastIndex
        font.pixelSize: 11

        background: Rectangle {
            color: "#0d0f14"
            radius: 6
        }
        contentItem: Text {
            leftPadding: 10
            text: sessionSelect.displayText
            color: "#e2e7f0"
            font: sessionSelect.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    // ── Power ────────────────────────────────────────────────────────────────
    //  Words, not symbols. These were "⏻" and "⟳"; U+23FB is in almost no
    //  ordinary text font - not DejaVu, not Liberation, not Noto Sans - so
    //  whether the shutdown button showed a power icon or an empty box came
    //  down to which font Qt happened to fall back to on that machine. Two
    //  words always render, and say plainly what the button does.
    Row {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 16
        spacing: 8

        Rectangle {
            width: shutLabel.implicitWidth + 28; height: 36; radius: 8
            color: shutMouse.pressed ? "#f38ba8" : "#0d0f14"
            Text {
                id: shutLabel
                anchors.centerIn: parent
                text: "Desligar"
                color: shutMouse.pressed ? "#07080b" : "#f38ba8"
                font.pixelSize: 12
            }
            MouseArea {
                id: shutMouse
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: sddm.powerOff()
            }
        }

        Rectangle {
            width: rebootLabel.implicitWidth + 28; height: 36; radius: 8
            color: rebootMouse.pressed ? "#f9e2af" : "#0d0f14"
            Text {
                id: rebootLabel
                anchors.centerIn: parent
                text: "Reiniciar"
                color: rebootMouse.pressed ? "#07080b" : "#f9e2af"
                font.pixelSize: 12
            }
            MouseArea {
                id: rebootMouse
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: sddm.reboot()
            }
        }
    }

    Component.onCompleted: {
        root.updateClock()
        if (userField.text === "")
            userField.forceActiveFocus()
        else
            passField.forceActiveFocus()
    }
}
