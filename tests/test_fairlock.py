from sm_typing import override

import unittest
import unittest.mock as mock

import socket
from fairlock import FairlockRead, FairlockWrite, FairlockServiceTimeout, FairlockDeadlock

class TestFairlock(unittest.TestCase):
    @override
    def setUp(self) -> None:
        sock_patcher = mock.patch('fairlock.socket', autospec=True)
        self.mock_socket = sock_patcher.start()
        os_patcher = mock.patch('fairlock.os', autospec=True)
        self.mock_os = os_patcher.start()
        time_patcher = mock.patch('fairlock.time', autospec=True)
        self.mock_time = time_patcher.start()

        self.addCleanup(mock.patch.stopall)


    def test_first_lock(self):
        """
        Single lock, starts the service
        """
        mock_sock = mock.MagicMock()
        self.mock_socket.socket.return_value = mock_sock
        mock_sock.connect.side_effect = [FileNotFoundError(), 0]
        mock_sock.recv.side_effect = [b'Foop']
        self.mock_os.system.side_effect = [0, 1, 0]
        self.mock_time.time.side_effect = [0, 0, 0]

        with FairlockWrite("test"):
            print("Hello World")

        self.mock_os.system.assert_called()

    def test_first_lock_timeout(self):
        """
        Single lock, starts the service but times out and raises exception
        """
        mock_sock = mock.MagicMock()
        self.mock_socket.socket.return_value = mock_sock
        mock_sock.connect.side_effect = [FileNotFoundError(), 0]
        mock_sock.recv.side_effect = [b'Foop']
        self.mock_os.system.side_effect = [0, 1, 1, 1, 0]
        self.mock_time.time.side_effect = [0, 1, 3]

        with self.assertRaises(FairlockServiceTimeout) as err:
            FairlockWrite("test")._ensure_service()

        self.mock_os.system.assert_called()

    def test_second_lock(self):
        """
        Single lock, used for the second time (no service start)
        """
        mock_sock = mock.MagicMock()
        self.mock_socket.socket.return_value = mock_sock
        mock_sock.connect.side_effect = [0]
        mock_sock.recv.side_effect = [b'Foop']

        with FairlockWrite("test"):
            print("Hello World")

        self.mock_os.system.assert_not_called()

    def test_two_locks(self):
        """
        Test two different locks, one inside the other
        """
        # Each connection attempt uses a new socket: the first one fails (the
        # service is not started yet), the second one works.
        mock_sock1a, mock_sock1b = mock.MagicMock(), mock.MagicMock()
        mock_sock2a, mock_sock2b = mock.MagicMock(), mock.MagicMock()
        self.mock_socket.socket.side_effect = [mock_sock1a, mock_sock1b, mock_sock2a, mock_sock2b]
        mock_sock1a.connect.side_effect = FileNotFoundError()
        mock_sock2a.connect.side_effect = FileNotFoundError()
        mock_sock1b.recv.side_effect = [b'Foop']
        mock_sock2b.recv.side_effect = [b'Foop']
        self.mock_os.system.side_effect = [0, 1, 0, 0, 1, 0]
        self.mock_time.time.side_effect = [0, 0, 0, 0, 0, 0]

        with FairlockWrite("test1"):
            print("Hello World")
            with FairlockWrite("test2"):
                print("Hello Again World")

    def test_double_lock_deadlock(self):
        """
        Test double usage of the same lock
        """
        mock_sock = mock.MagicMock()
        self.mock_socket.socket.return_value = mock_sock
        mock_sock.connect.side_effect = [FileNotFoundError(), 0]
        mock_sock.recv.side_effect = [b'Foop', b'Foop']
        self.mock_os.system.side_effect = [0, 1, 0, 0, 1, 0]
        self.mock_time.time.side_effect = [0, 0, 0, 0, 0, 0]

        with self.assertRaises(FairlockDeadlock) as err:
            with FairlockWrite("test") as l:
                n = FairlockWrite("test")
                self.assertEqual(l, n)
                # Real code would use another 'with FairlockWrite("test")' here but we cannot
                # do that because it insists on having a code block as a body, which would
                # then not be reached, causing a "Test code not fully covered" failure
                n.__enter__()
