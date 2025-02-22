import re
import math
import httpx
import os.path
import asyncio
import inspect

from datetime import datetime, timedelta
from string import Formatter
from functools import partial, wraps
from typing import Callable, List, Optional, Union

from pyrogram import Client, emoji, filters
from pyrogram.enums import ChatMemberStatus, MessageEntityType
from pyrogram.types import CallbackQuery, InlineKeyboardButton, Message, User

from ..config import sudoers


BTN_URL_REGEX = re.compile(r"(\[([^\[]+?)\]\(buttonurl:(?:/{0,2})(.+?)(:same)?\))")

SMART_OPEN = "“"
SMART_CLOSE = "”"
START_CHAR = ("'", '"', SMART_OPEN)


timeout = httpx.Timeout(40, pool=None)

http = httpx.AsyncClient(http2=True, timeout=timeout)


def run_async(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(func(*args, **kwargs))


def pretty_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


def aiowrap(func: Callable) -> Callable:
    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, pfunc)

    return run


async def check_perms(
    message: Union[CallbackQuery, Message],
    permissions: Optional[Union[list, str]],
    complain_missing_perms: bool,
    strings,
) -> bool:
    if isinstance(message, CallbackQuery):
        sender = partial(message.answer, show_alert=True)
        chat = message.message.chat
    else:
        sender = message.reply_text
        chat = message.chat
    # TODO: Cache all admin permissions in db.
    user = await chat.get_member(message.from_user.id)
    if user.status == ChatMemberStatus.OWNER:
        return True

    # No permissions specified, accept being an admin.
    if not permissions and user.status == ChatMemberStatus.ADMINISTRATOR:
        return True
    if user.status != ChatMemberStatus.ADMINISTRATOR:
        if complain_missing_perms:
            await sender(strings("no_admin_error"))
        return False

    if isinstance(permissions, str):
        permissions = [permissions]

    missing_perms = [
        permission
        for permission in permissions
        if not getattr(user.privileges, permission)
    ]

    if not missing_perms:
        return True
    if complain_missing_perms:
        await sender(
            strings("no_permission_error").format(permissions=", ".join(missing_perms))
        )
    return False


sudofilter = filters.user(sudoers)


async def time_extract(m: Message, t: str) -> Optional[datetime]:
    if t[-1] in ["m", "h", "d"]:
        unit = t[-1]
        num = t[:-1]
        if not num.isdigit():
            await m.reply_text("Invalid amount specified")
            return None

        if unit == "m":
            return datetime.now() + timedelta(minutes=int(num))
        elif unit == "h":
            return datetime.now() + timedelta(hours=int(num))
        elif unit == "d":
            return datetime.now() + timedelta(days=int(num))
        else:
            return None

    await m.reply_text("Invalid time format. Use 'h'/'m'/'d' ")
    return None


def remove_escapes(text: str) -> str:
    res = ""
    is_escaped = False
    for char in text:
        if is_escaped:
            res += char
            is_escaped = False
        elif char == "\\":
            is_escaped = True
        else:
            res += char
    return res


def split_quotes(text: str) -> List:
    if not any(text.startswith(char) for char in START_CHAR):
        return text.split(None, 1)
    counter = 1  # ignore first char -> is some kind of quote
    while counter < len(text):
        if text[counter] == "\\":
            counter += 1
        elif text[counter] == text[0] or (
            text[0] == SMART_OPEN and text[counter] == SMART_CLOSE
        ):
            break
        counter += 1
    else:
        return text.split(None, 1)

    rest = text[counter + 1 :].strip()
    if not key:
        key = text[0] + text[0]
    return list(filter(None, [key, rest]))


def button_parser(markdown_note):
    note_data = ""
    buttons = []
    if markdown_note is None:
        return note_data, buttons
    if markdown_note.startswith("/") or markdown_note.startswith("!"):
        args = markdown_note.split(None, 2)
        markdown_note = args[2]
    prev = 0
    for match in BTN_URL_REGEX.finditer(markdown_note):
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and markdown_note[to_check] == "\\":
            n_escapes += 1
            to_check -= 1

        if n_escapes % 2 == 0:
            if bool(match.group(4)) and buttons:
                buttons[-1].append(
                    InlineKeyboardButton(text=match.group(2), url=match.group(3))
                )
            else:
                buttons.append(
                    [InlineKeyboardButton(text=match.group(2), url=match.group(3))]
                )
            note_data += markdown_note[prev : match.start(1)]
            prev = match.end(1)

        else:
            note_data += markdown_note[prev:to_check]
            prev = match.start(1) - 1

    note_data += markdown_note[prev:]

    return note_data, buttons


class BotCommands:
    def __init__(self):
        self.commands = {}

    def add_command(
        self,
        command: str,
        category: str,
        description_key: str = None,
        context_location: str = None,
    ):
        if not context_location:
            # If context_location is not defined, get context from file name who added the command

            cwd = os.getcwd()
            frame = inspect.stack()[1]

            fname = frame.filename

            if fname.startswith(cwd):
                fname = fname[len(cwd) + 1 :]
            context_location = fname.split(os.path.sep)[2].split(".")[
                0
            ]  # eduu/plugins/<context>.py
        if description_key is None:
            description_key = f"{command}_description"
        if self.commands.get(category) is None:
            self.commands[category] = []
        self.commands[category].append(
            dict(
                command=command,
                description_key=description_key,
                context=context_location,
            )
        )

    def get_commands_message(self, strings_manager, category: str = None):
        # TODO: Add pagination support.
        if category is None:
            cmds_list = []
            for category in self.commands:
                cmds_list += self.commands[category]
        else:
            cmds_list = self.commands[category]

        res = (
            strings_manager("command_category_title").format(
                category=strings_manager(category)
            )
            + "\n\n"
        )

        cmds_list.sort(key=lambda k: k["command"])

        for cmd in cmds_list:
            res += f"<b>/{cmd['command']}</b> - <i>{strings_manager(cmd['description_key'], context=cmd['context'])}</i>\n"

        return res


commands = BotCommands()


def get_emoji_regex():
    e_list = [
        getattr(emoji, e).encode("unicode-escape").decode("ASCII")
        for e in dir(emoji)
        if not e.startswith("_")
    ]
    # to avoid re.error excluding char that start with '*'
    e_sort = sorted([x for x in e_list if not x.startswith("*")], reverse=True)
    # Sort emojis by length to make sure multi-character emojis are
    # matched first
    pattern_ = f"({'|'.join(e_sort)})"
    return re.compile(pattern_)


async def get_target_user(c: Client, m: Message) -> User:
    if m.reply_to_message:
        return m.reply_to_message.from_user
    msg_entities = m.entities[1] if m.text.startswith("/") else m.entities[0]
    return await c.get_users(
        msg_entities.user.id
        if msg_entities.type == MessageEntityType.TEXT_MENTION
        else int(m.command[1])
        if m.command[1].isdecimal()
        else m.command[1]
    )


async def get_reason_text(c: Client, m: Message) -> Message:
    reply = m.reply_to_message
    spilt_text = m.text.split
    if not reply and len(spilt_text()) >= 3:
        return spilt_text(None, 2)[2]
    elif reply and len(spilt_text()) >= 2:
        return spilt_text(None, 1)[1]
    else:
        return None


EMOJI_PATTERN = get_emoji_regex()


async def shell_exec(code):
    process = await asyncio.create_subprocess_shell(
        code, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )

    stdout = (await process.communicate())[0].decode().strip()
    return stdout, process


def get_format_keys(string: str) -> List[str]:
    """Return a list of formatting keys present in string."""
    return [i[1] for i in Formatter().parse(string) if i[1] is not None]
