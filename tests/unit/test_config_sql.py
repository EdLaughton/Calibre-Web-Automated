# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "config_sql.py"


def _load_config_sql_module():
    logger_instance = types.SimpleNamespace(
        info=mock.Mock(),
        warning=mock.Mock(),
        error=mock.Mock(),
        debug=mock.Mock(),
    )

    cps_package = types.ModuleType("cps")
    cps_package.__path__ = []  # type: ignore[attr-defined]

    constants_module = types.ModuleType("cps.constants")
    constants_module.DEFAULT_MAIL_SERVER = "mail.example.com"
    constants_module.DEFAULT_PORT = 8083
    constants_module.ADMIN_USER_SIDEBAR = 0
    constants_module.LDAP_AUTH_SIMPLE = 0
    constants_module.EXTENSIONS_UPLOAD = ["epub", "mobi"]
    constants_module.UPDATE_STABLE = 0
    constants_module.ROLE_ADMIN = 1
    constants_module.ROLE_DOWNLOAD = 2
    constants_module.ROLE_VIEWER = 4
    constants_module.ROLE_UPLOAD = 8
    constants_module.ROLE_EDIT = 16
    constants_module.ROLE_PASSWD = 32
    constants_module.ROLE_EDIT_SHELFS = 64
    constants_module.ROLE_DELETE_BOOKS = 128
    constants_module.DETAIL_RANDOM = 0
    constants_module.SUPPORTED_CALIBRE_BINARIES = []

    logger_module = types.ModuleType("cps.logger")
    logger_module.DEFAULT_LOG_LEVEL = 20
    logger_module.LOG_TO_STDOUT = "-"
    logger_module.LOG_TO_STDERR = "stderr"
    logger_module.DEFAULT_ACCESS_LOG = "access.log"
    logger_module.create = lambda: logger_instance

    subproc_wrapper_module = types.ModuleType("cps.subproc_wrapper")
    subproc_wrapper_module.process_wait = lambda *args, **kwargs: 0

    string_helper_module = types.ModuleType("cps.string_helper")
    string_helper_module.strip_whitespaces = lambda value: value

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_module.Column = lambda *args, **kwargs: None
    sqlalchemy_module.String = lambda *args, **kwargs: None
    sqlalchemy_module.Integer = lambda *args, **kwargs: None
    sqlalchemy_module.SmallInteger = lambda *args, **kwargs: None
    sqlalchemy_module.Boolean = lambda *args, **kwargs: None
    sqlalchemy_module.BLOB = lambda *args, **kwargs: None
    sqlalchemy_module.JSON = lambda *args, **kwargs: None
    sqlalchemy_module.exists = lambda *args, **kwargs: None

    sqlalchemy_exc_module = types.ModuleType("sqlalchemy.exc")
    sqlalchemy_exc_module.OperationalError = type("OperationalError", (Exception,), {})

    sqlalchemy_sql_module = types.ModuleType("sqlalchemy.sql")
    sqlalchemy_expression_module = types.ModuleType("sqlalchemy.sql.expression")
    sqlalchemy_expression_module.text = lambda value: value

    sqlalchemy_orm_module = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_module.declarative_base = lambda: type("Base", (), {})

    cryptography_module = types.ModuleType("cryptography")
    cryptography_exceptions_module = types.ModuleType("cryptography.exceptions")
    cryptography_fernet_module = types.ModuleType("cryptography.fernet")
    cryptography_fernet_module.Fernet = lambda *args, **kwargs: None

    sys.modules["cps"] = cps_package
    sys.modules["cps.constants"] = constants_module
    sys.modules["cps.logger"] = logger_module
    sys.modules["cps.subproc_wrapper"] = subproc_wrapper_module
    sys.modules["cps.string_helper"] = string_helper_module
    sys.modules["sqlalchemy"] = sqlalchemy_module
    sys.modules["sqlalchemy.exc"] = sqlalchemy_exc_module
    sys.modules["sqlalchemy.sql"] = sqlalchemy_sql_module
    sys.modules["sqlalchemy.sql.expression"] = sqlalchemy_expression_module
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_module
    sys.modules["cryptography"] = cryptography_module
    sys.modules["cryptography.exceptions"] = cryptography_exceptions_module
    sys.modules["cryptography.fernet"] = cryptography_fernet_module

    spec = importlib.util.spec_from_file_location("cps.config_sql", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cps.config_sql"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_get_book_path_defaults_to_calibre_dir_when_split_flag_is_missing():
    module = _load_config_sql_module()
    config = module.ConfigSQL()
    config.config_calibre_dir = "/calibre-library"

    assert config.get_book_path() == "/calibre-library"


def test_get_book_path_prefers_split_dir_when_split_library_is_enabled():
    module = _load_config_sql_module()
    config = module.ConfigSQL()
    config.config_calibre_dir = "/calibre-library"
    config.config_calibre_split = True
    config.config_calibre_split_dir = "/books"

    assert config.get_book_path() == "/books"
