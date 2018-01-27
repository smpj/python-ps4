# -*- coding: utf-8 -*-
from __future__ import print_function

import binascii
import logging
import socket

from construct import (Bytes, Const, Int32ul, Padding, Struct)
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA

_LOGGER = logging.getLogger(__name__)

PUBLIC_KEY = (
    '-----BEGIN PUBLIC KEY-----\n'
    'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxfAO/MDk5ovZpp7xlG9J\n'
    'JKc4Sg4ztAz+BbOt6Gbhub02tF9bryklpTIyzM0v817pwQ3TCoigpxEcWdTykhDL\n'
    'cGhAbcp6E7Xh8aHEsqgtQ/c+wY1zIl3fU//uddlB1XuipXthDv6emXsyyU/tJWqc\n'
    'zy9HCJncLJeYo7MJvf2TE9nnlVm1x4flmD0k1zrvb3MONqoZbKb/TQVuVhBv7SM+\n'
    'U5PSi3diXIx1Nnj4vQ8clRNUJ5X1tT9XfVmKQS1J513XNZ0uYHYRDzQYujpLWucu\n'
    'ob7v50wCpUm3iKP1fYCixMP6xFm0jPYz1YQaMV35VkYwc40qgk3av0PDS+1G0dCm\n'
    'swIDAQAB\n'
    '-----END PUBLIC KEY-----')


class Connection(object):
    """The TCP connection class."""
    def __init__(self, host, credential=None, port=997):
        self._host = host
        self._credential = credential
        self._port = port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._cipher = None
        self._decipher = None
        self._random_seed = \
            b'\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

    def connect(self):
        """Open the connection."""
        self._socket.connect((self._host, self._port))
        self._send_hello_request()
        data = self._recv_hello_request()
        self._set_crypto_init_vector(data.seed)
        self._send_handshake_request(data.seed)

    def disconnect(self):
        """Close the connection."""
        self._reset_crypto_init_vector()

    def login(self):
        """Login."""
        self._send_login_request()
        msg = self._recv_msg()
        msg = self._decipher.decrypt(msg)
        _LOGGER.debug('RX: %s %s', len(msg), binascii.hexlify(msg))

    def standby(self):
        """Request standby."""
        self._send_standby_request()
        msg = self._recv_msg()
        msg = self._decipher.decrypt(msg)
        _LOGGER.debug('RX: %s %s', len(msg), binascii.hexlify(msg))

    def start_title(self, title_id):
        """Start an application/game title."""
        self._send_boot_request(title_id)
        msg = self._recv_msg()
        msg = self._decipher.decrypt(msg)
        _LOGGER.debug('RX: %s %s', len(msg), binascii.hexlify(msg))

    def _send_msg(self, msg):
        _LOGGER.debug('TX: %s %s', len(msg), binascii.hexlify(msg))
        self._socket.send(msg)

    def _recv_msg(self):
        msg = self._socket.recv(1024)
        _LOGGER.debug('RX: %s %s', len(msg), binascii.hexlify(msg))
        return msg

    def _set_crypto_init_vector(self, init_vector):
        self._cipher = AES.new(self._random_seed, AES.MODE_CBC, init_vector)
        self._decipher = AES.new(self._random_seed, AES.MODE_CBC, init_vector)

    def _reset_crypto_init_vector(self):
        self._cipher = None
        self._decipher = None

    def _get_public_key_rsa(self):
        key = RSA.importKey(PUBLIC_KEY)
        public_key = key.publickey()
        return public_key

    def _send_hello_request(self):
        fmt = Struct(
            'length' / Const(b'\x1c\x00\x00\x00'),
            'type' / Const(b'\x70\x63\x63\x6f'),
            'version' / Const(b'\x00\x00\x02\x00'),
            'dummy' / Padding(16),
        )

        msg = fmt.build({})
        self._send_msg(msg)

    def _recv_hello_request(self):
        fmt = Struct(
            'length' / Int32ul,
            'type' / Int32ul,
            'version' / Int32ul,
            'dummy' / Bytes(8),
            'seed' / Bytes(16),
        )

        msg = self._recv_msg()
        data = fmt.parse(msg)
        return data

    def _send_handshake_request(self, seed):
        fmt = Struct(
            'length' / Const(b'\x18\x01\x00\x00'),
            'type' / Const(b'\x20\x00\x00\x00'),
            'key' / Bytes(256),
            'seed' / Bytes(16),
        )

        recipient_key = self._get_public_key_rsa()
        cipher_rsa = PKCS1_OAEP.new(recipient_key)
        key = cipher_rsa.encrypt(self._random_seed)

        _LOGGER.debug('key %s', binascii.hexlify(key))

        msg = fmt.build({'key': key, 'seed': seed})
        self._send_msg(msg)

    def _send_login_request(self):
        fmt = Struct(
            'length' / Const(b'\x80\x01\x00\x00'),
            'type' / Const(b'\x1e\x00\x00\x00'),
            'pass_code' / Const(b'\x00\x00\x00\x00'),
            'magic_number' / Const(b'\x01\x02\x00\x00'),
            'account_id' / Bytes(64),
            'app_label' / Bytes(256),
            'os_version' / Bytes(16),
            'model' / Bytes(16),
            'pin_code' / Bytes(16),
        )

        config = {
            'app_label': b'PlayStation'.ljust(256, b'\x00'),
            'account_id': self._credential.encode().ljust(64, b'\x00'),
            'os_version': b'4.4'.ljust(16, b'\x00'),
            'model': b'PS4 Waker'.ljust(16, b'\x00'),
            'pin_code': b''.ljust(16, b'\x00'),
        }

        _LOGGER.debug('config %s', config)

        msg = fmt.build(config)
        msg = self._cipher.encrypt(msg)
        self._send_msg(msg)

    def _send_standby_request(self):
        fmt = Struct(
            'length' / Const(b'\x08\x00\x00\x00'),
            'type' / Const(b'\x1a\x00\x00\x00'),
            'dummy' / Padding(8),
        )

        msg = fmt.build({})
        msg = self._cipher.encrypt(msg)
        self._send_msg(msg)

    def _send_boot_request(self, title_id):
        fmt = Struct(
            'length' / Const(b'\x18\x00\x00\x00'),
            'type' / Const(b'\x0a\x00\x00\x00'),
            'title_id' / Bytes(16),
            'dummy' / Padding(8),
        )

        msg = fmt.build({'title_id': title_id.encode().ljust(16, b'\x00')})
        msg = self._cipher.encrypt(msg)
        self._send_msg(msg)