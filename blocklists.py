"""
blocklists.py — Word/pattern blocklists with configurable actions.

Supports patterns:
  ?  → matches one non-whitespace character
  *  → matches any non-whitespace characters
  ** → matches any characters (including spaces)
"""

import logging
import re
from collections import defaultdict

from datetime import timedelta

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import admin_only, get_chat_lang
from approval import is_approved
from strings import t

logger = logging.getLogger(__name__)

# ─── Per-chat blocklist settings ─────────────────────────────────────────────
# {chat_id: {mode, delete, reason, triggers: {pattern: reason}}}
_bl_settings: dict[int, dict] = {}


def _get_settings(chat_id: int) -> dict:
    if chat_id not in _bl_settings:
        _bl_settings[chat_id] = {
            "mode": "mute",       # nothing/ban/mute/kick/warn/tban/tmute
            "mode_dur": 0,        # duration for tban/tmute
            "delete": True,       # delete blocklisted messages
            "reason": "",         # default warn/action reason
            "triggers": {},       # {pattern_str: reason_str}
            "_compiled": {},      # {pattern_str: compiled_regex}
        }
    return _bl_settings[chat_id]


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert a blocklist pattern to a compiled regex.

    ?  → one non-whitespace char
    *  → any non-whitespace chars
    ** → any characters (including spaces)
    """
    # Escape everything first, then convert our special tokens
    # We need to handle ** before * so we use placeholders
    result = ""
    i = 0
    while i < len(pattern):
        if i + 1 < len(pattern) and pattern[i] == "*" and pattern[i + 1] == "*":
            result += "PLACEHOLDER_DOUBLESTAR"
            i += 2
        elif pattern[i] == "*":
            result += "PLACEHOLDER_STAR"
            i += 1
        elif pattern[i] == "?":
            result += "PLACEHOLDER_QUESTION"
            i += 1
        else:
            result += pattern[i]
            i += 1

    # Escape regex special chars
    result = re.escape(result)

    # Replace placeholders with regex patterns
    result = result.replace("PLACEHOLDER_DOUBLESTAR", ".*")
    result = result.replace("PLACEHOLDER_STAR", r"\S*")
    result = result.replace("PLACEHOLDER_QUESTION", r"\S")

    return re.compile(result, re.IGNORECASE)


def _compile_trigger(settings: dict, pattern: str) -> None:
    """Compile and cache a trigger pattern."""
    settings["_compiled"][pattern] = _pattern_to_regex(pattern)


# ─── Message checker (called for every group message) ───────────────────────

async def check_blocklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if a message matches any blocklist trigger."""
    if not update.effective_message or not update.effective_user:
        return
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    settings = _get_settings(chat_id)

    if not settings["triggers"]:
        return

    # Skip approved users
    if is_approved(chat_id, user.id):
        return

    # Get message text (including captions)
    text = ""
    msg = update.effective_message
    if msg.text:
        text = msg.text
    elif msg.caption:
        text = msg.caption

    if not text:
        return

    # Check all triggers
    matched_trigger = None
    matched_reason = None
    for pattern, reason in settings["triggers"].items():
        compiled = settings["_compiled"].get(pattern)
        if not compiled:
            _compile_trigger(settings, pattern)
            compiled = settings["_compiled"][pattern]

        if compiled.search(text):
            matched_trigger = pattern
            matched_reason = reason or settings.get("reason", "")
            break

    if not matched_trigger:
        return

    lang = get_chat_lang(chat_id)
    logger.info(
        "Blocklist triggered by %s (%s) in %s: pattern '%s'",
        user.id, user.full_name, chat_id, matched_trigger,
    )

    # Delete the message if configured
    if settings.get("delete", True):
        try:
            await msg.delete()
        except (BadRequest, Forbidden):
            pass

    # Take action
    mode = settings["mode"]
    name = user.full_name

    try:
        if mode == "nothing":
            pass
        elif mode == "ban":
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                t(lang, "bl_action_ban", user=name, reason=matched_reason),
                parse_mode="Markdown",
            )
        elif mode == "mute":
            await context.bot.restrict_chat_member(
                chat_id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await context.bot.send_message(
                chat_id,
                t(lang, "bl_action_mute", user=name, reason=matched_reason),
                parse_mode="Markdown",
            )
        elif mode == "kick":
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.unban_chat_member(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                t(lang, "bl_action_kick", user=name, reason=matched_reason),
                parse_mode="Markdown",
            )
        elif mode == "tban":
            dur = settings.get("mode_dur", 0) or 300
            from antiflood import format_duration
            await context.bot.ban_chat_member(
                chat_id, user.id, until_date=timedelta(seconds=dur)
            )
            await context.bot.send_message(
                chat_id,
                t(lang, "bl_action_tban", user=name, dur=format_duration(dur), reason=matched_reason),
                parse_mode="Markdown",
            )
        elif mode == "tmute":
            dur = settings.get("mode_dur", 0) or 300
            from antiflood import format_duration
            await context.bot.restrict_chat_member(
                chat_id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=timedelta(seconds=dur),
            )
            await context.bot.send_message(
                chat_id,
                t(lang, "bl_action_tmute", user=name, dur=format_duration(dur), reason=matched_reason),
                parse_mode="Markdown",
            )
        elif mode == "warn":
            await context.bot.send_message(
                chat_id,
                t(lang, "bl_action_warn", user=name, reason=matched_reason),
                parse_mode="Markdown",
            )
    except (BadRequest, Forbidden) as exc:
        logger.warning("Blocklist action failed in %s: %s", chat_id, exc)


# ─── Admin command handlers ─────────────────────────────────────────────────

@admin_only
async def addblocklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addblocklist <trigger> <optional reason>"""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "addblocklist_usage"))
        return

    # Parse: could be a quoted phrase or single word
    raw = update.message.text.split(None, 1)  # split off command
    if len(raw) < 2:
        await update.message.reply_text(t(lang, "addblocklist_usage"))
        return

    rest = raw[1].strip()

    # Check for quoted trigger
    if rest.startswith('"'):
        end_quote = rest.find('"', 1)
        if end_quote == -1:
            trigger = rest.strip('"')
            reason = ""
        else:
            trigger = rest[1:end_quote]
            reason = rest[end_quote + 1:].strip()
    else:
        parts = rest.split(None, 1)
        trigger = parts[0]
        reason = parts[1] if len(parts) > 1 else ""

    trigger = trigger.lower()
    settings["triggers"][trigger] = reason
    _compile_trigger(settings, trigger)

    await update.message.reply_text(
        t(lang, "addblocklist_done", trigger=trigger), parse_mode="Markdown"
    )


@admin_only
async def rmblocklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/rmblocklist <trigger>"""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "rmblocklist_usage"))
        return

    trigger = " ".join(context.args).lower().strip('"')
    if trigger in settings["triggers"]:
        del settings["triggers"][trigger]
        settings["_compiled"].pop(trigger, None)
        await update.message.reply_text(
            t(lang, "rmblocklist_done", trigger=trigger), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(t(lang, "rmblocklist_notfound", trigger=trigger))


@admin_only
async def unblocklistall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unblocklistall — remove all triggers (creator only)."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    settings["triggers"] = {}
    settings["_compiled"] = {}
    await update.message.reply_text(
        t(lang, "unblocklistall_done"), parse_mode="Markdown"
    )


@admin_only
async def blocklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/blocklist — list all triggers."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not settings["triggers"]:
        await update.message.reply_text(t(lang, "blocklist_empty"))
        return

    lines = [t(lang, "blocklist_title", chat=chat.title or str(chat.id))]
    for trigger, reason in settings["triggers"].items():
        if reason:
            lines.append(f"  • `{trigger}` — {reason}")
        else:
            lines.append(f"  • `{trigger}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def blocklistmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/blocklistmode <action> — set the action for blocklist violations."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "blocklistmode_usage"))
        return

    action = context.args[0].lower()
    valid = ("nothing", "ban", "mute", "kick", "warn", "tban", "tmute")
    if action not in valid:
        await update.message.reply_text(t(lang, "blocklistmode_invalid"))
        return

    settings["mode"] = action

    # Parse optional duration for tban/tmute
    if action in ("tban", "tmute") and len(context.args) >= 2:
        from antiflood import parse_duration
        dur = parse_duration(context.args[1])
        if dur and dur > 0:
            settings["mode_dur"] = dur

    await update.message.reply_text(
        t(lang, "blocklistmode_set", mode=action), parse_mode="Markdown"
    )


@admin_only
async def blocklistdelete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/blocklistdelete <yes/no/on/off>"""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "blocklistdelete_usage"))
        return

    val = context.args[0].lower()
    if val in ("yes", "on"):
        settings["delete"] = True
        await update.message.reply_text(
            t(lang, "blocklistdelete_set", val="ON"), parse_mode="Markdown"
        )
    elif val in ("no", "off"):
        settings["delete"] = False
        await update.message.reply_text(
            t(lang, "blocklistdelete_set", val="OFF"), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(t(lang, "blocklistdelete_usage"))


@admin_only
async def setblocklistreason_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setblocklistreason <reason>"""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "setblocklistreason_usage"))
        return

    reason = " ".join(context.args)
    settings["reason"] = reason
    await update.message.reply_text(
        t(lang, "setblocklistreason_done", reason=reason), parse_mode="Markdown"
    )


@admin_only
async def resetblocklistreason_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resetblocklistreason — reset reason to default."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    settings["reason"] = ""
    await update.message.reply_text(
        t(lang, "resetblocklistreason_done"), parse_mode="Markdown"
    )
