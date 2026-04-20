import imaplib
import email
from email.header import decode_header
import asyncio
from telegram import Bot
from dotenv import load_dotenv
import os
from lxml import html
import re
from datetime import datetime, timedelta
import traceback
import time

load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USERNAME")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(token=TELEGRAM_TOKEN)

# 직원 정보 로드
staffs = []
i = 1
while True:
    chat_id = os.getenv(f"TELEGRAM_STAFF_{i}_CHAT_ID")
    team = os.getenv(f"TELEGRAM_STAFF_{i}_TEAM")
    use_day = os.getenv(f"TELEGRAM_STAFF_{i}_USE_DAY")
    status = os.getenv(f"TELEGRAM_STAFF_{i}_STATUS")

    if not chat_id or not team:
        break

    use_day_list = []
    if use_day and use_day != "전체":
        use_day_list = [int(day.strip()) for day in use_day.split(",")]

    status_list = []
    if status and status != "전체":
        status_list = [s.strip() for s in status.split(",")]

    staffs.append({
        "chat_id": chat_id,
        "team": team,
        "use_day": use_day_list if use_day_list else "전체",
        "status": status_list if status_list else "전체"
    })

    i += 1

print("✅ 직원 정보 로드 완료")

menu_translation = {
    "컷": "C",
    "펌": "P",
    "컬러": "CL",
    "클리닉": "TM",
    "이미지 헤어 컨설팅": "컨설팅"
}

def get_filtered_dates():
    today = datetime.today()
    return {
        0: today.strftime("%m.%d"),
        1: (today + timedelta(days=1)).strftime("%m.%d"),
        2: (today + timedelta(days=2)).strftime("%m.%d"),
        3: (today + timedelta(days=3)).strftime("%m.%d"),
        4: (today + timedelta(days=4)).strftime("%m.%d"),
        5: (today + timedelta(days=5)).strftime("%m.%d"),
        6: (today + timedelta(days=6)).strftime("%m.%d"),
    }

# -------------------------------
# Gmail 연결 (1회)
# -------------------------------
def connect_mail():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASSWORD)
    mail.select("inbox")
    print("✅ Gmail 연결 완료")
    return mail

# -------------------------------
# 메일 처리 (기존 로직 유지)
# -------------------------------
async def process_new_mail(mail):
    status, messages = mail.search(None, '(UNSEEN FROM "naverbooking_noreply@navercorp.com")')

    if status != "OK":
        return

    for num in messages[0].split():
        mail.store(num, '+FLAGS', '\\Seen')

        status, msg_data = mail.fetch(num, "(RFC822)")

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])

                subject, encoding = decode_header(msg["Subject"] or "")[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8", errors="replace")

                if "[네이버 예약]" not in subject:
                    continue

                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()

                        if content_type in ["text/plain", "text/html"]:
                            body = part.get_payload(decode=True)
                            if not body:
                                continue

                            body = body.decode(errors="replace")
                            tree = html.fromstring(body)
                            text_content = tree.text_content()

                            # 상태
                            reservation_status = None
                            if "예약을 취소" in text_content:
                                reservation_status = "취소"
                            elif "새로운 예약이 확정" in text_content:
                                reservation_status = "추가"
                            elif "입금대기" in text_content:
                                reservation_status = "입금대기"

                            # 디자이너
                            designer_name = None
                            match = re.search(r"(\S+)\s*(실장|디자이너)", text_content)
                            if match:
                                designer_name = match.group(1)

                            # 날짜
                            usage_time = None
                            match = re.search(r"\d{4}\.\d{2}\.\d{2}\.\(.*?\)\s*(오전|오후)\s*\d{1,2}:\d{2}", text_content)
                            if match:
                                usage_time = '.'.join(match.group(0).split('.')[1:])

                            # 메뉴
                            reservation_menu = re.findall(r"(\S+)\s*예약금", text_content)
                            reservation_menu = [menu_translation.get(m, m) for m in reservation_menu]

                            # 메시지 구성
                            message = ""
                            if designer_name:
                                message += f"{designer_name} / "
                            if usage_time:
                                message += f"{usage_time} "
                            if reservation_menu:
                                message += f"{' '.join(reservation_menu)} "
                            if reservation_status:
                                message += f"{reservation_status} 되었습니다."

                            if not message:
                                continue

                            # 필터링
                            filtered_dates = get_filtered_dates()

                            for staff in staffs:
                                if staff["team"] != "전체" and staff["team"] != designer_name:
                                    continue

                                if staff["use_day"] != "전체" and usage_time:
                                    date_part = usage_time.split()[0]
                                    if not any(filtered_dates[d] in date_part for d in staff["use_day"]):
                                        continue

                                if staff["status"] != "전체" and reservation_status not in staff["status"]:
                                    continue

                                await bot.send_message(chat_id=staff["chat_id"], text=message)
                                print(f"📨 전송: {message}")

# -------------------------------
# IDLE 루프
# -------------------------------
async def idle_loop():
    mail = connect_mail()

    while True:
        try:
            print("📡 IDLE 대기 중...")
            mail.send(b'IDLE\r\n')
            mail.readline()

            start = time.time()

            while True:
                if time.time() - start > 540:  # 9분
                    mail.send(b'DONE\r\n')
                    break

                resp = mail.readline()

                if resp and b'EXISTS' in resp:
                    print("📬 새 메일 감지!")
                    await process_new_mail(mail)

        except Exception as e:
            print("❌ 오류:", e)

            try:
                mail.logout()
            except:
                pass

            time.sleep(10)
            mail = connect_mail()

# -------------------------------
# 실행
# -------------------------------
if __name__ == "__main__":
    asyncio.run(idle_loop())
