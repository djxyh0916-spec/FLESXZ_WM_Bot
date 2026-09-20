import os
import io
import asyncio

from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, MessageHandler, ContextTypes, filters


BOT_TOKEN = "".join(os.environ.get("BOT_TOKEN", "").split())
WATERMARK = "@FLESXZPD"

# 暂存正在接收的相册
album_cache = {}
album_tasks = {}


def add_watermark(image_data):
    image = Image.open(io.BytesIO(image_data)).convert("RGBA")

    watermark = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(watermark)

    font_size = max(40, image.width // 18)

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

    layer_width = text_width + 40
    layer_height = text_height + 40

    text_layer = Image.new(
        "RGBA",
        (layer_width, layer_height),
        (0, 0, 0, 0)
    )

    text_draw = ImageDraw.Draw(text_layer)

    # 黑色阴影
    text_draw.text(
        (22, 22),
        WATERMARK,
        font=font,
        fill=(0, 0, 0, 90)
    )

    # 白色半透明
    text_draw.text(
        (20, 20),
        WATERMARK,
        font=font,
        fill=(255, 255, 255, 150)
    )

    # 斜着旋转
    rotated = text_layer.rotate(
        25,
        expand=True,
        resample=Image.Resampling.BICUBIC
    )

    # 放到图片正中央
    x = (image.width - rotated.width) // 2
    y = (image.height - rotated.height) // 2

    watermark.alpha_composite(rotated, (x, y))

    image = Image.alpha_composite(image, watermark)

    output = io.BytesIO()
    output.name = "watermarked.jpg"

    image.convert("RGB").save(
        output,
        format="JPEG",
        quality=92
    )

    return output.getvalue()


async def process_single(update, context):
    message = update.effective_message

    if not message or not message.photo:
        return

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    data = await file.download_as_bytearray()

    result = add_watermark(data)

    output = io.BytesIO(result)
    output.name = "watermarked.jpg"

    await context.bot.send_photo(
        chat_id=message.chat_id,
        photo=output,
        caption=message.caption or ""
    )


async def process_album(album_id, chat_id, context):
    # 等待一下，让同一相册里的图片全部到达
    await asyncio.sleep(1.5)

    album = album_cache.pop(album_id, [])

    if not album:
        return

    # 按原来的顺序排列
    album.sort(key=lambda x: x[0])

    media = []

    for _, photo_file_id, caption in album:
        file = await context.bot.get_file(photo_file_id)
        data = await file.download_as_bytearray()

        result = add_watermark(data)

        media.append(
            InputMediaPhoto(
                media=io.BytesIO(result),
                caption=caption or ""
            )
        )

    # Telegram 一次最多发送 10 张
    for i in range(0, len(media), 10):
        batch = media[i:i + 10]
        await context.bot.send_media_group(
            chat_id=chat_id,
            media=batch
        )

    album_tasks.pop(album_id, None)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.photo:
        return

    # 如果是 Telegram 相册
    if message.media_group_id:
        album_id = message.media_group_id

        if album_id not in album_cache:
            album_cache[album_id] = []

        album_cache[album_id].append(
            (
                message.message_id,
                message.photo[-1].file_id,
                message.caption or ""
            )
        )

        # 第一次收到这一组图片时，启动处理任务
        if album_id not in album_tasks:
            album_tasks[album_id] = asyncio.create_task(
                process_album(
                    album_id,
                    message.chat_id,
                    context
                )
            )

    else:
        # 普通单张图片
        await process_single(update, context)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN 没有设置")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )

    print("FLESXZ Watermark Bot 正在运行...")

    app.run_polling()


if __name__ == "__main__":
    main()
