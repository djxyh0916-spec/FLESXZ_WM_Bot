import os
import io
import asyncio
import uuid

from PIL import Image, ImageDraw, ImageFont

from telegram import (
    Update,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================
# 基本设置
# =========================

BOT_TOKEN = "".join(os.environ.get("BOT_TOKEN", "").split())

ADMIN_ID = 6044925673

CHANNEL_ID = "@FLESXZPD"

WATERMARK = "@FLESXZPD"


# =========================
# 临时数据
# =========================

# 等待处理的相册
album_cache = {}

# 相册延迟处理任务
album_tasks = {}

# 等待管理员审核的投稿
pending_submissions = {}


# =========================
# 水印
# =========================

def add_watermark(image_bytes):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    watermark = Image.new("RGBA", image.size, (0, 0, 0, 0))

    draw = ImageDraw.Draw(watermark)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    try:
        font_size = max(40, image.width // 18)
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), WATERMARK, font=font)

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    layer = Image.new(
        "RGBA",
        (text_width + 50, text_height + 50),
        (0, 0, 0, 0),
    )

    layer_draw = ImageDraw.Draw(layer)

    # 半透明白色水印
    layer_draw.text(
        (25, 25),
        WATERMARK,
        font=font,
        fill=(255, 255, 255, 155),
    )

    # 轻微阴影，让水印更清楚
    layer_draw.text(
        (27, 27),
        WATERMARK,
        font=font,
        fill=(0, 0, 0, 80),
    )

    # 斜着旋转
    rotated = layer.rotate(
        25,
        expand=True,
        resample=Image.Resampling.BICUBIC,
    )

    # 放到图片正中央
    x = (image.width - rotated.width) // 2
    y = (image.height - rotated.height) // 2

    watermark.alpha_composite(rotated, (x, y))

    result = Image.alpha_composite(image, watermark)

    output = io.BytesIO()
    output.name = "watermarked.jpg"

    result.convert("RGB").save(
        output,
        format="JPEG",
        quality=92,
    )

    return output.getvalue()


# =========================
# 审核按钮
# =========================

def review_keyboard(submission_id):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ 发布",
                    callback_data=f"publish:{submission_id}",
                ),
                InlineKeyboardButton(
                    "❌ 拒绝",
                    callback_data=f"reject:{submission_id}",
                ),
            ]
        ]
    )


# =========================
# 投稿格式整理
# =========================

def format_submission(text):

    if not text:
        return "出售 / 求购请联系：@Jackky547"

    lines = []

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("出售物品"):
            lines.append("📦 " + line)

        elif line.startswith("价格") or line.startswith("价"):
            lines.append("💰 " + line)

        elif line.startswith("位置"):
            lines.append("📍 " + line)

        elif line.startswith("联系方式"):
            lines.append("📞 " + line)

        elif line.startswith("交易方式"):
            lines.append("🚚 " + line)

        else:
            lines.append(line)

    lines.append("")
    lines.append("出售 / 求购请联系：@Jackky547")

    return "\n".join(lines)


# =========================
# /start
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

await update.message.reply_text(
    "👋 欢迎投稿到【富力二手闲置】\n\n"
    "📸 第一步：发送商品图片\n"
    "支持一张或多张图片，最多10张。\n\n"
    "📝 第二步：发送商品信息\n\n"
    "【出售】\n"
    "📦 出售物品：\n"
    "💰 价格：\n"
    "📍 位置：\n"
    "📞 联系方式：\n"
    "🚚 交易方式：\n\n"
    "【求购】\n"
    "🔎 求购物品：\n"
    "💰 预算：\n"
    "📍 位置：\n"
    "📞 联系方式：\n"
    "🚚 交易方式：\n\n"
    "━━━━━━━━━━━━\n\n"
    "📋 投稿后先由管理员审核\n"
    "✅ 审核通过后发布到频道\n\n"
    "📋 出售 / 求购请联系：@FLESXZ_WM_Bot\n"
    "👤 人工服务：@Jackky547"
)




# =========================
# 下载图片
# =========================

async def download_photo(message, context):

    photo = message.photo[-1]

    file = await context.bot.get_file(photo.file_id)

    data = await file.download_as_bytearray()

    return bytes(data)


# =========================
# 单张图片
# =========================

async def process_single_photo(message, context):

    original = await download_photo(message, context)

    watermarked = add_watermark(original)

    submission_id = uuid.uuid4().hex[:10]

    caption = format_submission(message.caption or "")

    pending_submissions[submission_id] = {
        "type": "single",
        "items": [
            {
                "data": watermarked,
                "caption": caption,
            }
        ],
    }

    photo_file = io.BytesIO(watermarked)

    photo_file.name = f"{submission_id}.jpg"

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_file,
        caption=caption,
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text="📋 新投稿，请审核：",
        reply_markup=review_keyboard(submission_id),
    )


# =========================
# 相册延迟处理
# =========================

async def process_album_later(album_id, context):

    try:

        # 等待 Telegram 把相册图片全部发送过来
        await asyncio.sleep(3)

        album = album_cache.pop(album_id, [])

        album_tasks.pop(album_id, None)

        if not album:
            return

        # 按消息顺序排列
        album.sort(key=lambda x: x["message_id"])

        processed_items = []

        for item in album:

            original = await download_photo(
                item["message"],
                context,
            )

            watermarked = add_watermark(original)

            processed_items.append(
                {
                    "data": watermarked,
                    "caption": item["caption"],
                }
            )

        submission_id = uuid.uuid4().hex[:10]

        # 找第一条有效文字
        final_caption = ""

        for item in processed_items:

            if item["caption"]:
                final_caption = item["caption"]
                break

        final_caption = format_submission(final_caption)

        # 只有第一张图片保留文字
        for i in range(len(processed_items)):

            if i == 0:
                processed_items[i]["caption"] = final_caption
            else:
                processed_items[i]["caption"] = None

        pending_submissions[submission_id] = {
            "type": "album",
            "items": processed_items,
        }

        # =========================
        # 发给管理员审核
        # =========================

        media = []

        for i, item in enumerate(processed_items):

            file = io.BytesIO(item["data"])

            file.name = f"{submission_id}_{i + 1}.jpg"

            media.append(
                InputMediaPhoto(
                    media=file,
                    caption=item["caption"],
                )
            )

        await context.bot.send_media_group(
            chat_id=ADMIN_ID,
            media=media,
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📋 收到 {len(processed_items)} 张图片（相册）\n\n请审核是否发布：",
            reply_markup=review_keyboard(submission_id),
        )

    except asyncio.CancelledError:
        return

    except Exception as e:

        print("处理相册失败：", e)


# =========================
# 接收图片
# =========================

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message

    if not message or not message.photo:
        return

    # =========================
    # 如果是相册
    # =========================

    if message.media_group_id:

        album_id = message.media_group_id

        if album_id not in album_cache:
            album_cache[album_id] = []

        album_cache[album_id].append(
            {
                "message": message,
                "message_id": message.message_id,
                "caption": message.caption or "",
            }
        )

        # 如果之前有等待任务，取消
        old_task = album_tasks.get(album_id)

        if old_task:
            old_task.cancel()

        # 重新等待 3 秒
        album_tasks[album_id] = asyncio.create_task(
            process_album_later(
                album_id,
                context,
            )
        )

        return

    # =========================
    # 普通单张图片
    # =========================

    await process_single_photo(
        message,
        context,
    )


# =========================
# 审核按钮
# =========================

async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    # 只有管理员可以审核
    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "你没有审核权限",
            show_alert=True,
        )

        return

    action, submission_id = query.data.split(":", 1)

    submission = pending_submissions.get(submission_id)

    if not submission:

        await query.edit_message_text(
            "⚠️ 这条投稿已经失效或处理过了。"
        )

        return

    # =========================
    # 拒绝
    # =========================

    if action == "reject":

        pending_submissions.pop(
            submission_id,
            None,
        )

        await query.edit_message_text(
            "❌ 已拒绝这条投稿。"
        )

        return

    # =========================
    # 发布
    # =========================

    if action == "publish":

        await query.edit_message_text(
            "⏳ 正在发布，请稍等……"
        )

        try:

            # =========================
            # 发布单张图片
            # =========================

            if submission["type"] == "single":

                item = submission["items"][0]

                photo_file = io.BytesIO(
                    item["data"]
                )

                photo_file.name = f"{submission_id}.jpg"

                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=photo_file,
                    caption=item["caption"],
                )

            # =========================
            # 发布相册
            # =========================

            else:

                media = []

                for i, item in enumerate(
                    submission["items"]
                ):

                    photo_file = io.BytesIO(
                        item["data"]
                    )

                    photo_file.name = (
                        f"{submission_id}_{i + 1}.jpg"
                    )

                    media.append(
                        InputMediaPhoto(
                            media=photo_file,
                            caption=item["caption"],
                        )
                    )

                await context.bot.send_media_group(
                    chat_id=CHANNEL_ID,
                    media=media,
                )

            # 删除等待审核数据
            pending_submissions.pop(
                submission_id,
                None,
            )

            await query.edit_message_text(
                "✅ 已发布到富力二手闲置频道"
            )

        except Exception as e:

            print("发布失败：", e)

            await query.edit_message_text(
                "❌ 发布失败\n\n"
                "请检查机器人是否有权限在频道发布消息。"
            )


# =========================
# 启动机器人
# =========================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN 没有设置"
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            receive_photo,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            review_callback,
        )
    )

    print("FLESXZ Watermark Bot 已启动")

    app.run_polling()


if __name__ == "__main__":
    main()
