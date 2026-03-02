"""
antiraid.py — Antiraid: auto-tempban new joins during raid attacks.
"""

import logging
import time
from collections import defaultdict
from datetime import timedelta

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import admin_only, get_chat_lang
from antiflood import parse_duration, format_duration
from strings import t

logger = logging.getLogger(__name__)

# ─── Per-chat antiraid settings ──────────────────────────────────────────────
# {chat_id: {enabled, end_time, raid_duration, action_duration, auto_threshold}}
_raid_settings: dict[int, dict] = {}

# ─── Join tracking for auto-antiraid ─────────────────────────────────────────
# {chat_id: [timestamps of recent joins]}
_join_log: dict[int, list[float]] = defaultdict(list)


def _get_settings(chat_id: int) -> dict:
    """Return or initialise antiraid settings for a chat."""
    if chat_id not in _raid_settings:
        _raid_settings[chat_id] = {
            "enabled": False,
            "end_time": 0,           # Unix timestamp when antiraid auto-disables
            "raid_duration": 21600,  # How long antiraid stays on (default 6h)
            "action_duration": 3600, # How long to tempban new joiners (default 1h)
            "auto_threshold": 0,     # Joins per minute to auto-enable (0 = disabled)
        }
    return _raid_settings[chat_id]


# ─── New member handler ─────────────────────────────────────────────────────

async def check_raid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called on new chat members — tempban if antiraid is active."""
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        return
    if not update.message or not update.message.new_chat_members:
        return

    chat_id = update.effective_chat.id
    settings = _get_settings(chat_id)
    now = time.time()

    # ── Auto-antiraid: check join rate ───────────────────────────────────
    if settings["auto_threshold"] > 0 and not settings["enabled"]:
        _join_log[chat_id].append(now)
        # Keep only joins in the last 60 seconds
        _join_log[chat_id] = [ts for ts in _join_log[chat_id] if now - ts <= 60]
        if len(_join_log[chat_id]) >= settings["auto_threshold"]:
            settings["enabled"] = True
            settings["end_time"] = now + settings["raid_duration"]
            lang = get_chat_lang(chat_id)
            logger.warning(
                "Auto-antiraid enabled in %s — %d joins/min exceeded threshold %d",
                chat_id, len(_join_log[chat_id]), settings["auto_threshold"],
            )
            try:
                await context.bot.send_message(
                    chat_id,
                    t(lang, "antiraid_auto_enabled",
                      threshold=settings["auto_threshold"],
                      dur=format_duration(settings["raid_duration"])),
                    parse_mode="Markdown",
                )
            except (BadRequest, Forbidden):
                pass

    # ── Check if antiraid is active ──────────────────────────────────────
    if not settings["enabled"]:
        return

    # Auto-disable if duration has passed
    if settings["end_time"] > 0 and now > settings["end_time"]:
        settings["enabled"] = False
        lang = get_chat_lang(chat_id)
        try:
            await context.bot.send_message(
                chat_id,
                t(lang, "antiraid_expired"),
                parse_mode="Markdown",
            )
        except (BadRequest, Forbidden):
            pass
        return

    # ── Tempban each new member ──────────────────────────────────────────
    lang = get_chat_lang(chat_id)
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        try:
            await context.bot.ban_chat_member(
                chat_id,
                member.id,
                until_date=timedelta(seconds=settings["action_duration"]),
            )
            logger.info(
                "Antiraid: tempbanned %s (%s) in %s for %s",
                member.id, member.full_name, chat_id,
                format_duration(settings["action_duration"]),
            )
        except (BadRequest, Forbidden) as exc:
            logger.warning("Antiraid: could not ban %s in %s: %s", member.id, chat_id, exc)


# ─── Admin command handlers ─────────────────────────────────────────────────

@admin_only
async def antiraid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/antiraid <optional time/off/no> — toggle antiraid."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    # No args → toggle
    if not context.args:
        if settings["enabled"]:
            settings["enabled"] = False
            settings["end_time"] = 0
            await update.message.reply_text(
                t(lang, "antiraid_off"), parse_mode="Markdown"
            )
        else:
            settings["enabled"] = True
            settings["end_time"] = time.time() + settings["raid_duration"]
            await update.message.reply_text(
                t(lang, "antiraid_on", dur=format_duration(settings["raid_duration"])),
                parse_mode="Markdown",
            )
        return

    val = context.args[0].lower()

    if val in ("off", "no"):
        settings["enabled"] = False
        settings["end_time"] = 0
        await update.message.reply_text(
            t(lang, "antiraid_off"), parse_mode="Markdown"
        )
        return

    # Parse as duration
    dur = parse_duration(val)
    if dur and dur > 0:
        settings["enabled"] = True
        settings["raid_duration"] = dur
        settings["end_time"] = time.time() + dur
        await update.message.reply_text(
            t(lang, "antiraid_on", dur=format_duration(dur)),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(t(lang, "antiraid_usage"))


@admin_only
async def raidtime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/raidtime <time> — view or set antiraid duration."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(
            t(lang, "raidtime_current", dur=format_duration(settings["raid_duration"])),
            parse_mode="Markdown",
        )
        return

    dur = parse_duration(context.args[0])
    if dur and dur > 0:
        settings["raid_duration"] = dur
        await update.message.reply_text(
            t(lang, "raidtime_set", dur=format_duration(dur)),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(t(lang, "raidtime_usage"))


@admin_only
async def raidactiontime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/raidactiontime <time> — view or set tempban duration for raid joiners."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(
            t(lang, "raidactiontime_current", dur=format_duration(settings["action_duration"])),
            parse_mode="Markdown",
        )
        return

    dur = parse_duration(context.args[0])
    if dur and dur > 0:
        settings["action_duration"] = dur
        await update.message.reply_text(
            t(lang, "raidactiontime_set", dur=format_duration(dur)),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(t(lang, "raidactiontime_usage"))


@admin_only
async def autoantiraid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/autoantiraid <number/off/no> — set auto-antiraid threshold."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        if settings["auto_threshold"] > 0:
            await update.message.reply_text(
                t(lang, "autoantiraid_current", n=settings["auto_threshold"]),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                t(lang, "autoantiraid_off"), parse_mode="Markdown"
            )
        return

    val = context.args[0].lower()
    if val in ("0", "off", "no"):
        settings["auto_threshold"] = 0
        await update.message.reply_text(
            t(lang, "autoantiraid_disabled"), parse_mode="Markdown"
        )
        return

    try:
        n = int(val)
        if n <= 0:
            raise ValueError
        settings["auto_threshold"] = n
        await update.message.reply_text(
            t(lang, "autoantiraid_set", n=n), parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text(t(lang, "autoantiraid_usage"))
