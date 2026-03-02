"""
inactivity.py — Kick members inactive for 15+ days (except exempt groups).
"""

import logging
import os
import time

from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import get_chat_lang, is_admin
from welcome import get_all_users

logger = logging.getLogger(__name__)

INACTIVITY_DAYS = 15
INACTIVITY_SECONDS = INACTIVITY_DAYS * 86400
CHECK_INTERVAL_SECONDS = 6 * 3600  # Run every 6 hours

# Groups exempt from inactivity kicking (matched by GROUP_NAMES)
_EXEMPT_NAMES = {"chat"}  # Lowercase — the "Chat" group is exempt


def _get_exempt_ids() -> set[int]:
    """Build set of exempt group IDs from GROUP_NAMES env var."""
    from bot import GROUP_IDS, GROUP_NAMES
    exempt = set()
    for gid, gname in zip(GROUP_IDS, GROUP_NAMES):
        if gname.strip().lower() in _EXEMPT_NAMES:
            exempt.add(gid)
    return exempt


async def kick_inactive_users(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic job: kick users with no messages in the last 15 days."""
    exempt_ids = _get_exempt_ids()
    now = time.time()

    for chat_id, users in list(get_all_users.__wrapped__() if hasattr(get_all_users, '__wrapped__') else _iter_all_chats()):
        if chat_id in exempt_ids:
            continue

        for user_id, data in list(users.items()):
            last_msg = data.get("last_msg_time", 0)

            # Skip users who never sent a message but joined recently
            if last_msg == 0:
                join_date = data.get("join_date")
                if join_date:
                    import datetime as dt
                    join_ts = join_date.timestamp()
                    if now - join_ts < INACTIVITY_SECONDS:
                        continue
                else:
                    continue

            if last_msg > 0 and (now - last_msg) < INACTIVITY_SECONDS:
                continue

            # Skip admins
            try:
                if await is_admin(chat_id, user_id, context.bot):
                    continue
            except Exception:
                continue

            # Kick the user
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                logger.info(
                    "Inactivity kick: user %s from chat %s (inactive %d days)",
                    user_id, chat_id,
                    int((now - max(last_msg, 0)) / 86400),
                )
            except (BadRequest, Forbidden) as exc:
                logger.warning(
                    "Could not kick inactive user %s from %s: %s",
                    user_id, chat_id, exc,
                )


def _iter_all_chats():
    """Iterate over all tracked chat/user data."""
    from welcome import _users
    return list(_users.items())


async def kick_inactive_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue wrapper for the inactivity checker."""
    # Reimplemented inline to avoid the generator issue
    from welcome import _users

    exempt_ids = _get_exempt_ids()
    now = time.time()

    for chat_id in list(_users.keys()):
        if chat_id in exempt_ids:
            continue

        users = _users[chat_id]
        for user_id in list(users.keys()):
            data = users[user_id]
            last_msg = data.get("last_msg_time", 0)

            # Skip users who never sent a message but joined recently
            if last_msg == 0:
                join_date = data.get("join_date")
                if join_date:
                    join_ts = join_date.timestamp()
                    if now - join_ts < INACTIVITY_SECONDS:
                        continue
                else:
                    continue

            if last_msg > 0 and (now - last_msg) < INACTIVITY_SECONDS:
                continue

            # Skip admins
            try:
                if await is_admin(chat_id, user_id, context.bot):
                    continue
            except Exception:
                continue

            # Kick the user
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                logger.info(
                    "Inactivity kick: user %s from chat %s (inactive %d+ days)",
                    user_id, chat_id, INACTIVITY_DAYS,
                )
            except (BadRequest, Forbidden) as exc:
                logger.warning(
                    "Could not kick inactive user %s from %s: %s",
                    user_id, chat_id, exc,
                )
