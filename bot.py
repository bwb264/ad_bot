import os
import logging
import asyncio
import tempfile
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from groq import Groq
from gtts import gTTS
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip,
    VideoFileClip, concatenate_videoclips
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
import random

# ─── إعدادات ───────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

groq_client = Groq(api_key=GROQ_API_KEY)

# حالات المحادثة
WAITING_FOR_TEXT = 1

# ألوان الخلفيات الجاهزة
BACKGROUNDS = [
    {"name": "أزرق فاخر",   "gradient": [(10, 20, 60),   (30, 80, 160)]},
    {"name": "بنفسجي ذهبي", "gradient": [(40, 10, 80),   (160, 100, 20)]},
    {"name": "أخضر زمردي",  "gradient": [(5, 50, 30),    (20, 130, 80)]},
    {"name": "أحمر أنيق",   "gradient": [(80, 10, 10),   (180, 50, 30)]},
    {"name": "رمادي راقي",  "gradient": [(20, 20, 30),   (70, 70, 90)]},
]

# ─── توليد نص الإعلان ───────────────────────────────────────────────────────
def generate_ad_text(product_description: str) -> str:
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=600,
        messages=[
            {
                "role": "system",
                "content": "أنت خبير تسويق محترف متخصص في كتابة الإعلانات العربية الجذابة."
            },
            {
                "role": "user",
                "content": f"""اكتب نصاً إعلانياً احترافياً وجذاباً باللغة العربية لهذا المنتج.

وصف المنتج: {product_description}

متطلبات النص:
- مدته عند القراءة بصوت عالٍ لا تتجاوز 45 ثانية (حوالي 120 كلمة)
- ابدأ بجملة تشويقية قوية تجذب الانتباه
- اذكر المزايا الرئيسية بأسلوب مقنع
- اختتم بدعوة واضحة للعمل (call to action)
- استخدم لغة عربية فصيحة وسلسة ومناسبة للإعلانات
- لا تستخدم علامات ترقيم كثيرة أو أقواس أو نجوم
- اكتب النص فقط بدون أي تعليقات إضافية"""
            }
        ]
    )
    return response.choices[0].message.content.strip()


# ─── توليد الصوت ─────────────────────────────────────────────────────────────
async def generate_voice(text: str, output_path: str):
    tts = gTTS(text=text, lang="ar", slow=False)
    tts.save(output_path)


# ─── إنشاء خلفية متدرجة ──────────────────────────────────────────────────────
def create_gradient_background(width: int, height: int, color1: tuple, color2: tuple) -> np.ndarray:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        ratio = y / height
        r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
        g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
        b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
        img[y, :] = [r, g, b]
    return img


# ─── إنشاء الفيديو الإعلاني ──────────────────────────────────────────────────
def create_ad_video(product_image_path: str, audio_path: str, output_path: str):
    VIDEO_W, VIDEO_H = 1080, 1920  # نسبة 9:16 للسوشيال ميديا

    bg_data = random.choice(BACKGROUNDS)
    c1, c2 = bg_data["gradient"]

    # ── 1. الخلفية ─────────────────────────────────────────────────────────
    bg_array = create_gradient_background(VIDEO_W, VIDEO_H, c1, c2)
    bg_pil = Image.fromarray(bg_array)

    # ── 2. إضافة نقاط ضوئية دائرية للجمال ────────────────────────────────
    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(6):
        cx = random.randint(0, VIDEO_W)
        cy = random.randint(0, VIDEO_H)
        r  = random.randint(150, 400)
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            fill=(255, 255, 255, 18)
        )
    bg_pil = Image.alpha_composite(bg_pil.convert("RGBA"), overlay).convert("RGB")

    # ── 3. صورة المنتج ─────────────────────────────────────────────────────
    product_img = Image.open(product_image_path).convert("RGBA")
    MAX_W, MAX_H = int(VIDEO_W * 0.78), int(VIDEO_H * 0.48)
    product_img.thumbnail((MAX_W, MAX_H), Image.LANCZOS)

    # إطار ناعم حول الصورة
    pw, ph = product_img.size
    border = 14
    framed = Image.new("RGBA", (pw + border * 2, ph + border * 2), (255, 255, 255, 50))
    framed.paste(product_img, (border, border), product_img)

    fw, fh = framed.size
    prod_x = (VIDEO_W - fw) // 2
    prod_y = int(VIDEO_H * 0.08)
    bg_pil.paste(framed.convert("RGB"), (prod_x, prod_y), framed.split()[3])

    # ── 4. شريط نصي سفلي ──────────────────────────────────────────────────
    bar_h = int(VIDEO_H * 0.42)
    bar   = Image.new("RGBA", (VIDEO_W, bar_h), (0, 0, 0, 170))
    bg_pil.paste(bar, (0, VIDEO_H - bar_h), bar)

    # ── 5. حفظ الصورة الإطار ─────────────────────────────────────────────
    frame_path = output_path.replace(".mp4", "_frame.jpg")
    bg_pil.save(frame_path, quality=95)

    # ── 6. تجميع الفيديو ──────────────────────────────────────────────────
    audio_clip    = AudioFileClip(audio_path)
    duration      = audio_clip.duration + 1.5

    image_clip = (
        ImageClip(frame_path)
        .set_duration(duration)
        .set_audio(audio_clip)
    )
    image_clip.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp_audio.m4a",
        remove_temp=True,
        logger=None
    )

    # تنظيف
    if os.path.exists(frame_path):
        os.remove(frame_path)


# ─── معالجات البوت ───────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *مرحباً بك في بوت الإعلانات الذكي!*\n\n"
        "📸 أرسل لي *صورة المنتج* مع *وصف للمنتج* في نفس الرسالة\n\n"
        "وسأقوم بإنشاء إعلان فيديو احترافي لك! 🎬✨",
        parse_mode="Markdown"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال الصورة مع الكابشن"""
    message = update.message

    if not message.caption:
        await message.reply_text(
            "⚠️ الرجاء إرسال الصورة مع *وصف للمنتج* في حقل الكابشن.\n\n"
            "مثال: أرسل الصورة واكتب في الكابشن:\n"
            "_ساعة ذكية فاخرة، شاشة AMOLED، عمر بطارية 7 أيام، مقاومة للماء_",
            parse_mode="Markdown"
        )
        return

    product_desc = message.caption.strip()
    processing_msg = await message.reply_text("⏳ جارٍ معالجة طلبك...\n\n🤖 أكتب نص الإعلان...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            # ── تحميل الصورة ──────────────────────────────────────────────
            photo = message.photo[-1]
            photo_file = await photo.get_file()
            img_path = os.path.join(tmp_dir, "product.jpg")
            await photo_file.download_to_drive(img_path)

            # ── توليد النص ────────────────────────────────────────────────
            ad_text = generate_ad_text(product_desc)
            await processing_msg.edit_text(
                "⏳ جارٍ معالجة طلبك...\n\n✅ تم كتابة النص\n🎙️ جارٍ توليد الصوت..."
            )

            # ── توليد الصوت ───────────────────────────────────────────────
            audio_path = os.path.join(tmp_dir, "voice.mp3")
            await generate_voice(ad_text, audio_path)

            await processing_msg.edit_text(
                "⏳ جارٍ معالجة طلبك...\n\n✅ تم كتابة النص\n✅ تم توليد الصوت\n🎬 جارٍ إنشاء الفيديو..."
            )

            # ── إنشاء الفيديو ─────────────────────────────────────────────
            video_path = os.path.join(tmp_dir, "ad_video.mp4")
            create_ad_video(img_path, audio_path, video_path)

            await processing_msg.edit_text(
                "⏳ جارٍ معالجة طلبك...\n\n✅ تم كتابة النص\n✅ تم توليد الصوت\n✅ تم إنشاء الفيديو\n📤 جارٍ الإرسال..."
            )

            # ── إرسال الفيديو ─────────────────────────────────────────────
            caption = (
                f"🎬 *إعلانك جاهز!*\n\n"
                f"📝 *نص الإعلان:*\n_{ad_text}_\n\n"
                f"✨ _جاهز للنشر على منصات التواصل الاجتماعي_"
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
                f"❌ حدث خطأ أثناء المعالجة:\n`{str(e)}`\n\nحاول مرة أخرى.",
                parse_mode="Markdown"
            )


async def handle_text_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 الرجاء إرسال *صورة المنتج* مع الوصف في الكابشن.",
        parse_mode="Markdown"
    )


# ─── تشغيل البوت ─────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_only))
    logger.info("✅ البوت يعمل...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
    
