import os
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

logging.basicConfig(level=logging.INFO)

# ✅ التوكن (لازم يكون في Railway باسم BOT_TOKEN)
TOKEN = os.environ.get("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود")

# ─── /start ─────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك!\n\n"
        "أرسل أي رسالة وسأرد عليك 👍"
    )

# ─── رد على أي رسالة ────────────────────
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📝 استلمت رسالتك:\n\n{update.message.text}"
    )

# ─── تشغيل البوت ────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
