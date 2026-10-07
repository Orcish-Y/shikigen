import errno
import socket
import sys
import unittest
from unittest.mock import MagicMock, call, patch

from app import desktop_network


class DesktopListenerTests(unittest.TestCase):
  def test_invalid_start_port_does_not_create_a_socket(self):
    with patch.object(desktop_network.socket, "socket") as create_listener:
      for start_port in (-1, 0, 65536):
        with self.subTest(start_port=start_port), self.assertRaises(ValueError):
          desktop_network.bind_listener(start_port)
      create_listener.assert_not_called()

  def test_only_occupied_and_windows_excluded_ports_are_retried(self):
    listeners = [MagicMock(spec=socket.socket) for _ in range(4)]
    for listener, error_code in zip(
      listeners[:-1], (errno.EADDRINUSE, 10048, 10013), strict=True
    ):
      listener.bind.side_effect = OSError(error_code, "injected bind error")
    with (
      patch.object(
        desktop_network.socket, "socket", side_effect=listeners
      ) as create_listener,
      self.assertLogs("app.desktop_network", level="WARNING") as warnings,
    ):
      bound_listener = desktop_network.bind_listener(48000)
    self.assertIs(bound_listener, listeners[-1])
    self.assertEqual(
      create_listener.call_args_list,
      [call(socket.AF_INET, socket.SOCK_STREAM)] * 4,
    )
    for offset, listener in enumerate(listeners):
      listener.bind.assert_called_once_with(("127.0.0.1", 48000 + offset))
      if sys.platform == "win32":
        listener.setsockopt.assert_called_once_with(
          socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
        )
      if listener is not bound_listener:
        listener.close.assert_called_once_with()
    bound_listener.setblocking.assert_called_once_with(False)
    bound_listener.close.assert_not_called()
    self.assertEqual(len(warnings.output), 1)
    self.assertIn("127.0.0.1:48002", warnings.output[0])
    bound_listener.close()

  def test_fatal_bind_error_is_propagated_and_socket_is_closed(self):
    listener = MagicMock(spec=socket.socket)
    bind_error = OSError(errno.EIO, "fatal bind error")
    listener.bind.side_effect = bind_error
    with patch.object(
      desktop_network.socket, "socket", return_value=listener
    ) as create_listener:
      with self.assertRaises(OSError) as raised:
        desktop_network.bind_listener(48000)
    self.assertIs(raised.exception, bind_error)
    create_listener.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    listener.close.assert_called_once_with()
    listener.setblocking.assert_not_called()

  @unittest.skipUnless(sys.platform == "win32", "Windows socket option")
  def test_exclusive_socket_option_error_closes_the_socket(self):
    listener = MagicMock(spec=socket.socket)
    option_error = OSError(errno.EIO, "socket option failed")
    listener.setsockopt.side_effect = option_error
    with patch.object(desktop_network.socket, "socket", return_value=listener):
      with self.assertRaises(OSError) as raised:
        desktop_network.bind_listener(48000)
    self.assertIs(raised.exception, option_error)
    listener.close.assert_called_once_with()
    listener.bind.assert_not_called()

  def test_nonblocking_setup_error_closes_the_bound_socket(self):
    listener = MagicMock(spec=socket.socket)
    setup_error = OSError(errno.EIO, "nonblocking setup failed")
    listener.setblocking.side_effect = setup_error
    with patch.object(desktop_network.socket, "socket", return_value=listener):
      with self.assertRaises(OSError) as raised:
        desktop_network.bind_listener(48000)
    self.assertIs(raised.exception, setup_error)
    listener.bind.assert_called_once_with(("127.0.0.1", 48000))
    listener.close.assert_called_once_with()

  def test_search_stops_at_maximum_port_and_closes_failed_sockets(self):
    listeners = [MagicMock(spec=socket.socket) for _ in range(2)]
    for listener in listeners:
      listener.bind.side_effect = OSError(errno.EADDRINUSE, "occupied")
    with patch.object(
      desktop_network.socket, "socket", side_effect=listeners
    ) as create_listener:
      with self.assertRaisesRegex(OSError, "No available backend port through 65535"):
        desktop_network.bind_listener(65534)
    self.assertEqual(create_listener.call_count, 2)
    for candidate_port, listener in zip((65534, 65535), listeners, strict=True):
      listener.bind.assert_called_once_with(("127.0.0.1", candidate_port))
      listener.close.assert_called_once_with()

  def test_real_occupied_listener_survives_and_selected_port_is_released(self):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as existing_listener:
      existing_listener.bind(("127.0.0.1", 0))
      existing_listener.listen(1)
      existing_listener.settimeout(2)
      occupied_port = existing_listener.getsockname()[1]
      with desktop_network.bind_listener(occupied_port) as bound_listener:
        bound_host, bound_port = bound_listener.getsockname()
        self.assertEqual(bound_host, "127.0.0.1")
        self.assertGreater(bound_port, occupied_port)
        self.assertFalse(bound_listener.getblocking())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as contender:
          contender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
          with self.assertRaises(OSError):
            contender.bind((bound_host, bound_port))
        with socket.create_connection((bound_host, occupied_port), timeout=2) as client:
          connection, _peer_address = existing_listener.accept()
          with connection:
            connection.sendall(b"existing service")
            self.assertEqual(client.recv(64), b"existing service")
      with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as replacement_listener:
        replacement_listener.bind((bound_host, bound_port))
