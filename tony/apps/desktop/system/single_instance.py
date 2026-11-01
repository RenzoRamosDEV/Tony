from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from tony.apps.desktop.instance_channel import CLIENT_TIMEOUT_MS, MAX_MESSAGE_BYTES, parse_message


def send_to_running(name: str, message: str) -> bool:
    """Send one message to the running instance; False when none answers in time."""
    client = QLocalSocket()
    client.connectToServer(name)
    if not client.waitForConnected(CLIENT_TIMEOUT_MS):
        return False
    client.write(f"{message}\n".encode())
    sent = client.waitForBytesWritten(CLIENT_TIMEOUT_MS)
    client.disconnectFromServer()
    return sent


class InstanceServer(QObject):
    """Serves the single-instance channel; emits `message` for each valid `show`/`focus`."""

    message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept)

    def serve(self, name: str) -> bool:
        if self._server.listen(name):
            return True
        QLocalServer.removeServer(name)
        return self._server.listen(name)

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        while (client := self._server.nextPendingConnection()) is not None:
            client.readyRead.connect(lambda client=client: self._read(client))
            client.disconnected.connect(client.deleteLater)

    def _read(self, client: QLocalSocket) -> None:
        raw = bytes(client.read(MAX_MESSAGE_BYTES + 1).data())
        client.disconnectFromServer()
        message = parse_message(raw)
        if message is not None:
            self.message.emit(message)
