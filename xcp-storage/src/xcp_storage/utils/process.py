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

import asyncio
from pathlib import Path
import subprocess

import xcp_storage.log as log

from xcp_storage.typing import (
    Callable,
    cast,
    List,
    Literal,
    Optional,
    overload,
    Tuple,
    Union,
)

# ==============================================================================

class CommandError(Exception):
    def __init__(self, code: Optional[int], cmd: str, reason: str) -> None:
        super().__init__("Command execution error.")
        self.code = code
        self.cmd = cmd
        self.reason = reason

def default_ret_code_callback(_stdout: str, _stderr: str, ret_code: int) -> int:
    return ret_code

# ------------------------------------------------------------------------------

@overload
def run_internal_command(
    args: List[str],
    *,
    simple: Literal[True] = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> str:
    ...

@overload
def run_internal_command(
    args: List[str],
    *,
    simple: Literal[False],
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Tuple[str, str, int]:
    ...

@overload
def run_internal_command(
    args: List[str],
    *,
    simple: bool,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Union[str, Tuple[str, str, int]]:
    ...

def run_internal_command(
    args: List[str],
    *,
    simple: bool = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Union[str, Tuple[str, str, int]]:
    try:
        result = subprocess.run( # noqa: UP022
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            encoding="utf-8"
        )
    except Exception as e:
        raise CommandError(None, str(args), reason=f"Failed to run command: `{e}`.") from e

    stdout, stderr = result.stdout, result.stderr

    if expected_ret_code is not None and result.returncode != expected_ret_code:
        if not quiet:
            log.error(f"Command `{' '.join(args)}` exited with code {result.returncode}: `{stderr.strip()}`.")
        raise CommandError(ret_code_callback(stdout, stderr, result.returncode), str(args), reason=stderr.strip())

    if simple:
        return stdout
    return stdout, stderr, result.returncode

# ------------------------------------------------------------------------------

@overload
def run_command(
    args: List[str],
    *,
    simple: Literal[True] = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> str:
    ...

@overload
def run_command(
    args: List[str],
    *,
    simple: Literal[False],
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Tuple[str, str, int]:
    ...

def run_command(
    args: List[str],
    *,
    simple: bool = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Union[str, Tuple[str, str, int]]:
    log.info(f"Running command `{' '.join(args)}`.")
    return run_internal_command(
        args,
        simple=simple,
        expected_ret_code=expected_ret_code,
        ret_code_callback=ret_code_callback,
        quiet=quiet
    )

# ------------------------------------------------------------------------------

@overload
async def run_internal_command_async(
    args: List[str],
    *,
    simple: Literal[True] = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> str:
    ...

@overload
async def run_internal_command_async(
    args: List[str],
    *,
    simple: Literal[False],
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Tuple[str, str, int]:
    ...

@overload
async def run_internal_command_async(
    args: List[str],
    *,
    simple: bool,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Union[str, Tuple[str, str, int]]:
    ...

async def run_internal_command_async(
    args: List[str],
    *,
    simple: bool = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Union[str, Tuple[str, str, int]]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_data, stderr_data = await process.communicate()

        stdout = stdout_data.decode("utf-8")
        stderr = stderr_data.decode("utf-8")
        ret_code = cast(int, process.returncode)
    except Exception as e:
        raise CommandError(None, str(args), reason=f"Failed to run command: `{e}`.") from e

    if expected_ret_code is not None and ret_code != expected_ret_code:
        if not quiet:
            log.error(f"Command `{' '.join(args)}` exited with code {ret_code}: `{stderr.strip()}`.")
        raise CommandError(ret_code_callback(stdout, stderr, ret_code), str(args), reason=stderr.strip())

    if simple:
        return stdout
    return stdout, stderr, ret_code

# ------------------------------------------------------------------------------

@overload
async def run_command_async(
    args: List[str],
    *,
    simple: Literal[True] = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> str:
    ...

@overload
async def run_command_async(
    args: List[str],
    *,
    simple: Literal[False],
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Tuple[str, str, int]:
    ...

async def run_command_async(
    args: List[str],
    *,
    simple: bool = True,
    expected_ret_code: Optional[int] = None,
    ret_code_callback: Callable[[str, str, int], int] = default_ret_code_callback,
    quiet: bool = False
) -> Union[str, Tuple[str, str, int]]:
    log.info(f"Running command `{' '.join(args)}`.")
    return await run_internal_command_async(
        args,
        simple=simple,
        expected_ret_code=expected_ret_code,
        ret_code_callback=ret_code_callback,
        quiet=quiet
    )

# ------------------------------------------------------------------------------

def get_process_cmdline(pid: int) -> List[str]:
    path = Path(f"/proc/{pid}/cmdline")
    try:
        return [arg.decode() for arg in path.read_bytes().split(b"\0") if arg]
    except Exception as e:
        log.info(f"Unable to get command line of PID `{pid}`: `{e}`.")
        return []
