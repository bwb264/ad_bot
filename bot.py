import os
import logging
import asyncio
import tempfile
import subprocess
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from groq import Groq
from gtts import gTTS
from PIL import Image, ImageDraw
import numpy as np
import random
import struct
import wave

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
groq_client    = Groq(api_key=GROQ_API_KEY)

BACKGROUNDS = [
    [(10, 20, 60),   (30, 80, 160)],
    [(40, 10, 80),   (160, 100, 20)],
    [(5, 50, 30),    (20, 130, 80)],
    [(80, 10, 10),   (180, 50, 30)],
    [(20, 20, 30),   (70, 70, 90)],
]

# ─── توليد نص الإعلان ────────────────────────────────────────────────────────
def generate_ad_text(product_description: str) -> str:
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=500,
        messages=[
            {"role": "system", "content": "أنت خبير تسويق محترف متخصص في كتابة الإعلانات العربية الجذابة."},
            {"role": "user", "content": f"""اكتب نصاً إعلانياً احترافياً باللغة العربية لهذا المنتج.
وصف المنتج: {product_description}
متطلبات:
- لا تتجاوز 100 كلمة
- ابدأ بجملة تشويقية
- اذكر المزايا الرئيسية
- اختتم بدعوة للعمل
- لا تستخدم أقواس أو نجوم
- اكتب النص فقط"""}
        ]
    )
    return response.choices[0].message.content.strip()

# ─── توليد الصوت ─────────────────────────────────────────────────────────────
async def generate_voice(text: str, output_path: str):
    tts = gTTS(text=text, lang="ar", slow=False)
    tts.save(output_path)

# ─── إنشاء صورة الإعلان ──────────────────────────────────────────────────────
def create_ad_image(product_image_path: str, output_path: str):
    VIDEO_W, VIDEO_H = 720, 1280
    c1, c2 = random.choice(BACKGROUNDS)

    # خلفية متدرجة
    bg = np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
    for y in range(VIDEO_H):
        r = y / VIDEO_H
        bg[y, :] = [
            int(c1[0]*(1-r) + c2[0]*r),
            int(c1[1]*(1-r) + c2[1]*r),
            int(c1[2]*(1-r) + c2[2]*r),
        ]
    bg_pil = Image.fromarray(bg)

    # نقاط ضوئية
    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(5):
        cx = random.randint(0, VIDEO_W)
        cy = random.randint(0, VIDEO_H)
        rv = random.randint(100, 300)
        draw.ellipse([(cx-rv, cy-rv),(cx+rv, cy+rv)], fill=(255,255,255,15))
    bg_pil = Image.alpha_composite(bg_pil.convert("RGBA"), overlay).convert("RGB")

    # صورة المنتج
    prod = Image.open(product_image_path).convert("RGBA")
    prod.thumbnail((int(VIDEO_W*0.8), int(VIDEO_H*0.5)), Image.LANCZOS)
    pw, ph = prod.size
    px = (VIDEO_W - pw) // 2
    py = int(VIDEO_H * 0.07)
    bg_pil.paste(prod, (px, py), prod)

    # شريط سفلي
    bar = Image.new("RGBA", (VIDEO_W, int(VIDEO_H*0.4)), (0,0,0,160))
    bg_pil.paste(bar, (0, VIDEO_H - int(VIDEO_H*0.4)), bar)

    bg_pil.save(output_path, quality=95)

# ─── دمج الصورة والصوت بـ ffmpeg ─────────────────────────────────────────────
def create_video_ffmpeg(image_path: str, audio_path: str, output_path: str):
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg error: {result.stderr}")

# ─── معالجات البوت ───────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *مرحباً بك في بوت الإعلانات الذكي!*\n\n"
        "📸 أرسل لي *صورة المنتج* مع *وصف للمنتج* في الكابشن\n\n"
        "وسأصنع لك فيديو إعلاني احترافي! 🎬✨",
        parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.caption:
        await message.reply_text(
            "⚠️ أرسل الصورة مع *وصف المنتج* في الكابشن.\n\n"
            "مثال: _ساعة ذكية فاخرة، شاشة AMOLED، عمر بطارية 7 أيام_",
            parse_mode="Markdown"
        )
        return

    product_desc = message.caption.strip()
    processing_msg = await message.reply_text("⏳ جارٍ المعالجة...\n\n🤖 أكتب نص الإعلان...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            # تحميل الصورة
            photo = message.photo[-1]
            photo_file = await photo.get_file()
            img_path = os.path.join(tmp_dir, "product.jpg")
            await photo_file.download_to_drive(img_path)

            # توليد النص
            ad_text = generate_ad_text(product_desc)
            await processing_msg.edit_text("⏳ جارٍ المعالجة...\n\n✅ تم النص\n🎙️ جارٍ توليد الصوت...")

            # توليد الصوت
            audio_path = os.path.join(tmp_dir, "voice.mp3")
            await generate_voice(ad_text, audio_path)
            await processing_msg.edit_text("⏳ جارٍ المعالجة...\n\n✅ تم النص\n✅ تم الصوت\n🎬 جارٍ إنشاء الفيديو...")

            # إنشاء صورة الإعلان
            frame_path = os.path.join(tmp_dir, "frame.jpg")
            create_ad_image(img_path, frame_path)

            # دمج الفيديو
            video_path = os.path.join(tmp_dir, "ad_video.mp4")
            create_video_ffmpeg(frame_path, audio_path, video_path)

            await processing_msg.edit_text("⏳ جارٍ المعالجة...\n\n✅ تم النص\n✅ تم الصوت\n✅ تم الفيديو\n📤 جارٍ الإرسال...")

            caption = (
                f"🎬 *إعلانك جاهز!*\n\n"
                f"📝 *نص الإعلان:*\n_{ad_text}_\n\n"
                f"✨ _جاهز للنشر على السوشيال ميديا_"
            )
            with open(video_path, "rb") as vf:
                await message.reply_video(
                    video=vf,
                    caption=caption,
                    parse_mode="Markdown",
                    supports_streaming=True
                )
            await processing_msg.delete()

        except Exception as e:
            logger.error(f"خطأ: {e}")
            await processing_msg.edit_text(
                f"❌ حدث خطأ:\n`{str(e)}`\n\nحاول مرة أخرى.",
                parse_mode="Markdown"
            )

async def handle_text_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 أرسل *صورة المنتج* مع الوصف في الكابشن.",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_only))
    logger.info("✅ البوت يعمل...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
        
