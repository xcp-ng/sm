#!/usr/bin/env python3
#
# Copyright (C) 2026  Vates SAS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import logging.handlers
import sys
from types import TracebackType

from xcp_storage.typing import (
    Any,
    List,
    Optional,
    Type,
)

# ==============================================================================

LOG_LEVEL = logging.DEBUG

LOG_TO_STDERR = True
LOG_TO_JOURNAL = False

# `LOG_LOCAL2` is mapped to "/var/log/SMlog".
LOG_SYSLOG_FACILITY = logging.handlers.SysLogHandler.LOG_LOCAL2

# ------------------------------------------------------------------------------

def debug(message: str, *args: Any, **kwargs: Any) -> None:
    _LOGGER.debug(message, *args, **kwargs)

def info(message: str, *args: Any, **kwargs: Any) -> None:
    _LOGGER.info(message, *args, **kwargs)

def warning(message: str, *args: Any, **kwargs: Any) -> None:
    _LOGGER.warning(message, *args, **kwargs)

def error(message: str, *args: Any, **kwargs: Any) -> None:
    _LOGGER.error(message, *args, **kwargs)

def critical(message: str, *args: Any, **kwargs: Any) -> None:
    _LOGGER.critical(message, *args, **kwargs)

# ------------------------------------------------------------------------------

def _configure_logger() -> None:
    _LOGGER.setLevel(LOG_LEVEL)

    handlers: List[logging.Handler] = []

    if LOG_TO_JOURNAL:
        handlers.append(logging.handlers.SysLogHandler(
            address="/dev/log",
            facility=LOG_SYSLOG_FACILITY
        ))

    if LOG_TO_STDERR:
        handlers.append(logging.StreamHandler(sys.stderr))

    formatter = logging.Formatter("XCP-storage: [%(process)d] - %(levelname)s - %(message)s")
    for handler in handlers:
        handler.setLevel(LOG_LEVEL)
        handler.setFormatter(formatter)
        _LOGGER.addHandler(handler)

    def _excepthook(
        exception_type: Type[BaseException],
        exception_value: BaseException,
        exception_traceback: Optional[TracebackType]
    ) -> None:
        if not issubclass(exception_type, KeyboardInterrupt):
            error("Unhandled exception.", exc_info=(exception_type, exception_value, exception_traceback))
        sys.__excepthook__(exception_type, exception_value, exception_traceback)
    sys.excepthook = _excepthook

# ------------------------------------------------------------------------------

_LOGGER = logging.getLogger()
_configure_logger()
