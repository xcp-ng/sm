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
import contextlib

# ==============================================================================

def cancel_event_loop_tasks(event_loop: asyncio.AbstractEventLoop) -> None:
    try:
        tasks = asyncio.all_tasks(event_loop)
    except AttributeError:
        # Workaround for python 3.6.
        tasks = asyncio.Task.all_tasks(event_loop) # type: ignore

    for task in tasks:
        task.cancel()

    event_loop.run_until_complete(asyncio.tasks.gather(*tasks, return_exceptions=True))
    event_loop.run_until_complete(event_loop.shutdown_asyncgens())

async def close_stream_writer(stream: asyncio.StreamWriter) -> None:
    with contextlib.suppress(Exception):
        if not stream.is_closing():
            stream.close()
            await stream.wait_closed()
