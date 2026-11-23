import os
import asyncio
import smtplib
import ssl
import mimetypes
import uuid
from datetime import timedelta
from email.message import EmailMessage
import httpx  # Используется для загрузки Gist
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPoll, MessageEntityTextUrl


def get_env(name: str, default: str = "") -> str:
    """Читает переменную окружения."""
    return os.getenv(name) or os.getenv(f"MORPH_{name}") or default


# --- НАСТРОЙКИ ИЗ ENVIRONMENT VARIABLES НА RENDER ---
API_ID = int(get_env("TG_API_ID", "0"))
API_HASH = get_env("TG_API_HASH")
SESSION_STRING = get_env("TG_SESSION")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = get_env("MAIL_SENDER")
SENDER_PASS = get_env("MAIL_PASS")
RECEIVER_EMAIL = get_env("MAIL_RECEIVER")
MAX_EMAIL_SIZE = 24 * 1024 * 1024  # 24 МБ (безопасный порог для 25 МБ лимита)

# Прямая ссылка на RAW-версию твоего Gist со списком VPN-каналов
VPN_GIST_URL = get_env("VPN_GIST_URL", "")

# Опциональный секретный ключ для URL (если задашь CRON_SECRET, вызывать нужно /run?key=...)
CRON_SECRET = get_env("CRON_SECRET", "")

# Порт, который автоматически назначает Render
PORT = int(os.getenv("PORT", "10000"))

RAM_PATH = os.path.join(os.getcwd(), "temp_media")
os.makedirs(RAM_PATH, exist_ok=True)

mail_queue = asyncio.Queue()
job_lock = asyncio.Lock()


async def fetch_vpn_channels_list():
    """Загружает список VPN-каналов из GitHub Gist."""
    if not VPN_GIST_URL:
        print("ℹ️ VPN_GIST_URL не задан. Все письма будут отправляться с темой Telegram.")
        return set()

    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            res = await http_client.get(VPN_GIST_URL)
            if res.status_code == 200:
                lines = res.text.splitlines()
                vpn_list = set()
                for line in lines:
                    item = line.strip().lstrip("@").lower()
                    if item:
                        vpn_list.add(item)
                print(f"📋 Загружен список VPN-каналов ({len(vpn_list)} шт.) из Gist")
                return vpn_list
            else:
                print(f"⚠️ Ошибка загрузки Gist: Статус {res.status_code}")
    except Exception as e:
        print(f"⚠️ Не удалось загрузить список VPN-каналов из Gist: {e}")

    return set()


async def send_mail_worker():
    while not mail_queue.empty():
        subject, html_body, files = await mail_queue.get()
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SENDER_EMAIL
            msg["To"] = RECEIVER_EMAIL
            msg.set_content("HTML format required.")
            msg.add_alternative(html_body, subtype="html")

            for f_data, f_name, cid in files:
                ctype, _ = mimetypes.guess_type(f_name)
                ctype = ctype or "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                msg.get_payload()[1].add_related(
                    f_data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=f_name,
                    cid=f"<{cid}>",
                )

            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
                server.login(SENDER_EMAIL, SENDER_PASS)
                server.send_message(msg)

            print(f"✅ Отправлено: {subject}")

            if not mail_queue.empty():
                await asyncio.sleep(5)
        except Exception as e:
            print(f"❌ Ошибка SMTP: {e}")
        finally:
            mail_queue.task_done()


def get_html_text(msg):
    if not msg:
        return ""
    raw_text = msg.message or ""
    if not raw_text:
        return ""

    if msg.entities:
        sorted_entities = sorted(msg.entities, key=lambda e: e.offset, reverse=True)
        html_text = raw_text
        for ent in sorted_entities:
            if isinstance(ent, MessageEntityTextUrl):
                start = ent.offset
                end = ent.offset + ent.length
                text_word = html_text[start:end]
                html_link = f'<a href="{ent.url}" style="color: #0088cc; text-decoration: underline;">{text_word}</a>'
                html_text = html_text[:start] + html_link + html_text[end:]
        return html_text.replace("\n", "<br>")

    html_text = msg.text_html if hasattr(msg, "text_html") and msg.text_html else raw_text
    return html_text.replace("\n", "<br>")


async def process_messages(client, messages, chat_entity, vpn_list, mark_read=False):
    if not messages:
        return
    first_msg = messages[0]
    chat_title = chat_entity.title

    chat_username = (getattr(chat_entity, "username", "") or "").lower()
    chat_id_str = str(chat_entity.id)

    is_vpn_channel = chat_username in vpn_list or chat_id_str in vpn_list
    email_subject = "VPN" if is_vpn_channel else "Telegram"

    if chat_username:
        base_url = f"https://t.me/{chat_username}"
    else:
        base_url = f"https://t.me/c/{chat_entity.id}"

    msg_with_text = next((m for m in messages if m.message), None)
    formatted_text = get_html_text(msg_with_text) if msg_with_text else ""

    files = []
    media_html = ""
    poll_html = ""

    total_size = sum(getattr(msg.file, "size", 0) for msg in messages if msg.media)

    for msg in messages:
        if not msg.media:
            continue

        if isinstance(msg.media, MessageMediaPoll):
            poll = msg.media.poll
            poll_type = "📊 Опрос" if not poll.quiz else "💡 Викторина"
            question = poll.question.text if hasattr(poll.question, "text") else str(poll.question)

            answers_list = ""
            for answer in poll.answers:
                answer_text = answer.text.text if hasattr(answer.text, "text") else str(answer.text)
                answers_list += f'<li style="margin-bottom: 5px;">🔹 {answer_text}</li>'

            poll_html += f"""
            <div style="background-color: #f4f7f9; border-left: 4px solid #0088cc; padding: 12px; margin-top: 15px; border-radius: 4px;">
                <strong style="color: #0088cc;">{poll_type}:</strong> <span style="font-size: 15px; font-weight: bold;">{question}</span>
                <ul style="list-style-type: none; padding-left: 5px; margin-top: 10px; margin-bottom: 0;">
                    {answers_list}
                </ul>
            </div>
            """
            continue

        file_size = getattr(msg.file, "size", 0)

        if total_size >= MAX_EMAIL_SIZE or file_size >= MAX_EMAIL_SIZE:
            f_name = getattr(msg.file, "name", "media_file") or "media_file"
            print(f"⚠️ Файл {f_name} ({round(file_size / (1024*1024), 2)} МБ) превышает лимит почты. Пропускаем.")
            media_html += f'<br><p style="color: #888;">⚠️ <i>Вложение пропущено (превышен лимит 25 МБ): {f_name}</i></p>'
        else:
            path = await msg.download_media(file=RAM_PATH)
            if path and os.path.exists(path):
                f_name = os.path.basename(path)
                cid = str(uuid.uuid4())
                with open(path, "rb") as f:
                    f_data = f.read()

                files.append((f_data, f_name, cid))
                os.remove(path)

                if f_name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    media_html += f'<br><img src="cid:{cid}" style="max-width: 100%;"><br>'
                elif f_name.lower().endswith((".mp3", ".ogg", ".wav", ".m4a")):
                    media_html += f'<br><p>🎵 Аудиофайл: {f_name}</p>'
                else:
                    media_html += f'<br><p>📎 Вложение: {f_name}</p>'

    local_time = first_msg.date + timedelta(hours=5)
    pub_date = local_time.strftime("%d.%m.%Y %H:%M:%S")

    reply_to_html = ""
    quoted_post_html = ""
    if first_msg.reply_to and first_msg.reply_to.reply_to_msg_id:
        reply_msg_id = first_msg.reply_to.reply_to_msg_id
        reply_to_html = f' | <a href="{base_url}/{reply_msg_id}" style="color: #0056b3; text-decoration: none;">в ответ</a>'

        try:
            parent_msg = await client.get_messages(chat_entity, ids=reply_msg_id)
            if parent_msg:
                parent_text = get_html_text(parent_msg)
                if not parent_text and parent_msg.media:
                    parent_text = "<i>[Медиавложение]</i>"

                quoted_post_html = f"""
                <blockquote style="margin: 0 0 15px 0; padding: 5px 0 5px 12px; border-left: 3px solid #0088cc; color: #555; background-color: #f9f9f9;">
                    <small style="color: #0088cc; font-weight: bold;">В ответ на post от {parent_msg.date.strftime('%d.%m.%Y')}:</small><br>
                    {parent_text}
                </blockquote>
                """
        except Exception as e:
            print(f"⚠️ Не удалось получить родительский пост #{reply_msg_id}: {e}")

    post_url = f"{base_url}/{first_msg.id}"

    html_body = f"""
    <html>
    <body>
        <h3>{chat_title}</h3>
        <p style="color: #666; font-size: 14px;">🕒 {pub_date}{reply_to_html}</p>
        <hr style="border: 0; border-top: 1px solid #eee; margin: 15px 0;">
        <div style="margin-bottom: 20px;">
            {quoted_post_html}
            {formatted_text}
        </div>
        {poll_html}
        {media_html}
        <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
        <small style="color: #999;">Ссылка на post: <a href="{post_url}">{post_url}</a></small>
    </body>
    </html>
    """

    await mail_queue.put((email_subject, html_body, files))

    if mark_read:
        await client.send_read_acknowledge(first_msg.chat_id, max_id=max(m.id for m in messages))


async def run_scraper_job():
    """Разовый полный цикл проверки Telegram и отправки всех писем."""
    if job_lock.locked():
        print("⏳ Задача уже выполняется, пропускаем повторный вызов.")
        return

    async with job_lock:
        print("🚀 Подключение к Telegram...")
        vpn_list = await fetch_vpn_channels_list()
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

        try:
            async with client:
                async for dialog in client.iter_dialogs():
                    if dialog.is_channel and dialog.unread_count > 0:
                        print(f"📥 Читаем {dialog.name}: {dialog.unread_count} новых")
                        chat_entity = await client.get_entity(dialog.id)
                        messages = await client.get_messages(dialog.id, limit=dialog.unread_count)

                        grouped = {}
                        ungrouped = []
                        for m in reversed(messages):
                            if m.grouped_id:
                                grouped.setdefault(m.grouped_id, []).append(m)
                            else:
                                ungrouped.append([m])

                        all_batches = list(grouped.values()) + ungrouped
                        for i, batch in enumerate(all_batches):
                            should_mark = i == len(all_batches) - 1
                            await process_messages(client, batch, chat_entity, vpn_list, mark_read=should_mark)

            print("🔌 Соединение с Telegram закрыто.")

            if not mail_queue.empty():
                print(f"📧 Начинаем отправку писем ({mail_queue.qsize()} шт.)...")
                await send_mail_worker()
            else:
                print("📭 Новых постов не найдено.")

            print("💤 Работа завершена. Ждём следующего вызова или засыпания контейнера.")
        except Exception as e:
            print(f"❌ Ошибка при выполнении задачи: {e}")


async def handle_http_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Минимальный встроенный HTTP-сервер для Render и cron-job.org."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not request_line:
            writer.close()
            return

        # Дочитываем заголовки
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not line or line == b"\r\n":
                break

        parts = request_line.decode("utf-8", errors="ignore").split()
        path = parts[1] if len(parts) > 1 else "/"

        # Проверка секретного ключа, если он задан в настройках Render
        if CRON_SECRET and f"key={CRON_SECRET}" not in path:
            body = b"Forbidden"
            response = (
                b"HTTP/1.1 403 Forbidden\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + body
            )
            writer.write(response)
            await writer.drain()
            writer.close()
            return

        # Запускаем проверку каналов в фоне (не блокируя ответ для cron-job.org)
        if not path.startswith("/favicon"):
            if job_lock.locked():
                body = b"Already running"
            else:
                asyncio.create_task(run_scraper_job())
                body = b"Started"
        else:
            body = b"OK"

        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    # При пробуждении контейнера от внешнего запроса сразу запускаем проверку и поднимаем порт
    server = await asyncio.start_server(handle_http_request, "0.0.0.0", PORT)
    print(f"🌐 HTTP-сервер запущен на порту {PORT} и готов принимать запросы от cron-job.org")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
        
