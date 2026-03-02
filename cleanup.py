"""
cleanup.py — Auto-delete service messages (joins, leaves, title changes, etc.).
"""

import logging

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def delete_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete any service/status message in groups."""
    if not update.effective_message:
        return
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        return

    try:
        await update.effective_message.delete()
    except (BadRequest, Forbidden):
        pass  # Bot may lack delete permission
