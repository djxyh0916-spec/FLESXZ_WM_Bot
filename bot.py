import os
import io

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters


BOT_TOKEN = "".join(os.environ.get("BOT_TOKEN", "").split())
WATERMARK = "富力二手闲置  @FLESXZPD"


async def add_watermark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.photo:
        return

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    data = await file.download_as_bytearray()

    image = Image.open(io.BytesIO(data)).convert("RGBA")
    draw = ImageDraw.Draw(image)

    font_size = max(24, image.width // 35)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            font_size
        )
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), WATERMARK, font=font)

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = image.width - text_width - 30
    y = image.height - text_height - 30

    # 阴影
    draw.text(
        (x + 2, y + 2),
        WATERMARK,
        font=font,
        fill=(0, 0, 0, 100)
    )

    # 白色半透明水印
    draw.text(
        (x, y),
        WATERMARK,
        font=font,
        fill=(255, 255, 255, 150)
    )

    output = io.BytesIO()
    output.name = "watermarked.jpg"

    image.convert("RGB").save(
        output,
        format="JPEG",
        quality=92
    )

    output.seek(0)

    await context.bot.send_photo(
        chat_id=message.chat_id,
        photo=output,
        caption=message.caption or ""
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN 没有设置")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.PHOTO, add_watermark)
    )

    print("FLESXZ Watermark Bot 正在运行...")

    app.run_polling()


if __name__ == "__main__":
    main()
