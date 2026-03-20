import os
import logging
import asyncio
import tempfile
import time
import requests
import base64
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from groq import Groq
from gtts import gTTS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")
SHOTSTACK_API_KEY = os.environ.get("SHOTSTACK_API_KEY", "")
SHOTSTACK_ENV     = "stage"  # sandbox مجاني

groq_client = Groq(api_key=GROQ_API_KEY)

# ─── توليد نص الإعلان ────────────────────────────────────────────────────────
def generate_ad_text(product_description: str) -> str:
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=400,
        messages=[
            {"role": "system", "content": "أنت خبير تسويق محترف متخصص في كتابة الإعلانات العربية الجذابة."},
            {"role": "user", "content": f"""اكتب نصاً إعلانياً احترافياً باللغة العربية لهذا المنتج.
وصف المنتج: {product_description}
متطلبات:
- لا تتجاوز 80 كلمة
- ابدأ بجملة تشويقية
- اذكر المزايا الرئيسية
- اختتم بدعوة للعمل
- لا تستخدم أقواس أو نجوم
- اكتب النص فقط بدون تعليقات"""}
        ]
    )
    return response.choices[0].message.content.strip()

# ─── رفع الصورة على Shotstack ─────────────────────────────────────────────────
def upload_image_to_shotstack(image_path: str) -> str:
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    headers = {
        "x-api-key": SHOTSTACK_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "url": f"data:image/jpeg;base64,{image_data}"
    }
    response = requests.post(
        f"https://api.shotstack.io/{SHOTSTACK_ENV}/assets",
        headers=headers,
        json=payload,
        timeout=30
    )
    if response.status_code not in [200, 201]:
        raise Exception("فشل رفع الصورة: " + response.text[:200])

    data = response.json()
    return data.get("data", {}).get("attributes", {}).get("url", "")

# ─── توليد الصوت ─────────────────────────────────────────────────────────────
def generate_voice_sync(text: str, output_path: str):
    tts = gTTS(text=text, lang="ar", slow=False)
    tts.save(output_path)

# ─── رفع الصوت على Shotstack ──────────────────────────────────────────────────
def upload_audio_to_shotstack(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        audio_data = base64.b64encode(f.read()).decode("utf-8")

    headers = {
        "x-api-key": SHOTSTACK_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "url": f"data:audio/mpeg;base64,{audio_data}"
    }
    response = requests.post(
        f"https://api.shotstack.io/{SHOTSTACK_ENV}/assets",
        headers=headers,
        json=payload,
        timeout=30
    )
    if response.status_code not in [200, 201]:
        raise Exception("فشل رفع الصوت: " + response.text[:200])

    data = response.json()
    return data.get("data", {}).get("attributes", {}).get("url", "")

# ─── إنشاء الفيديو عبر Shotstack ─────────────────────────────────────────────
def create_video_shotstack(image_url: str, audio_url: str, duration: float = 30) -> str:
    headers = {
        "x-api-key": SHOTSTACK_API_KEY,
        "Content-Type": "application/json"
    }

    # قالب الفيديو
    payload = {
        "timeline": {
            "background": "#000000",
            "tracks": [
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "image",
                                "src": image_url
                            },
                            "start": 0,
                            "length": duration,
                            "effect": "zoomIn",
                            "fit": "cover"
                        }
                    ]
                },
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "audio",
                                "src": audio_url,
                                "volume": 1
                            },
                            "start": 0,
                            "length": duration
                        }
                    ]
                }
            ]
        },
        "output": {
            "format": "mp4",
            "resolution": "hd",
            "aspectRatio": "9:16"
        }
    }

    response = requests.post(
        f"https://api.shotstack.io/{SHOTSTACK_ENV}/render",
        headers=headers,
        json=payload,
        timeout=30
    )

    if response.status_code not in [200, 201]:
        raise Exception("فشل انشاء الفيديو: " + response.text[:300])

    render_id = response.json()["response"]["id"]
    return render_id

# ─── انتظار اكتمال الفيديو ────────────────────────────────────────────────────
def wait_for_video(render_id: str, max_wait: int = 300) -> str:
    headers = {"x-api-key": SHOTSTACK_API_KEY}
    url = f"https://api.shotstack.io/{SHOTSTACK_ENV}/render/{render_id}"

    for _ in range(max_wait // 5):
        time.sleep(5)
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        status = data["response"]["status"]

        if status == "done":
            return data["response"]["url"]
        elif status == "failed":
            raise Exception("فشل إنشاء الفيديو في Shotstack")

    raise Exception("انتهت مدة الانتظار")

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
            await processing_msg.edit_text(
                "⏳ جارٍ المعالجة...\n\n✅ تم النص\n🎙️ جارٍ توليد الصوت..."
            )

            # توليد الصوت
            audio_path = os.path.join(tmp_dir, "voice.mp3")
            generate_voice_sync(ad_text, audio_path)
            await processing_msg.edit_text(
                "⏳ جارٍ المعالجة...\n\n✅ تم النص\n✅ تم الصوت\n☁️ جارٍ رفع الملفات..."
            )

            # رفع الصورة والصوت
            image_url = upload_image_to_shotstack(img_path)
            audio_url  = upload_audio_to_shotstack(audio_path)
            await processing_msg.edit_text(
                "⏳ جارٍ المعالجة...\n\n✅ تم النص\n✅ تم الصوت\n✅ تم الرفع\n🎬 جارٍ إنشاء الفيديو..."
            )

            # إنشاء الفيديو
            render_id = create_video_shotstack(image_url, audio_url, duration=35)
            await processing_msg.edit_text(
                "⏳ جارٍ المعالجة...\n\n✅ تم النص\n✅ تم الصوت\n✅ تم الرفع\n⏳ الفيديو يُعالج على السحابة..."
            )

            # انتظار الفيديو
            video_url = wait_for_video(render_id)
            await processing_msg.edit_text(
                "⏳ جارٍ المعالجة...\n\n✅ تم النص\n✅ تم الصوت\n✅ تم الرفع\n✅ تم الفيديو\n📤 جارٍ الإرسال..."
            )

            # تحميل الفيديو وإرساله
            video_response = requests.get(video_url, timeout=60)
            video_path = os.path.join(tmp_dir, "ad_video.mp4")
            with open(video_path, "wb") as f:
                f.write(video_response.content)

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
