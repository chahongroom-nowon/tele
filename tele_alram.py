import imaplib
import email
from email.header import decode_header
import time
from telegram import Bot
import asyncio
from dotenv import load_dotenv
import os
from lxml import html
import re
from datetime import datetime, timedelta
import traceback

# .env 파일에서 환경 변수 불러오기
load_dotenv()

# Gmail 로그인 정보
GMAIL_USER = os.getenv("GMAIL_USERNAME")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")

# 텔레그램 봇 정보
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 직원 정보
staffs = []

i = 1
while True:
    chat_id = os.getenv(f"TELEGRAM_STAFF_{i}_CHAT_ID")
    team = os.getenv(f"TELEGRAM_STAFF_{i}_TEAM")
    use_day = os.getenv(f"TELEGRAM_STAFF_{i}_USE_DAY")
    status = os.getenv(f"TELEGRAM_STAFF_{i}_STATUS")

    if not chat_id or not team:
        break  # chat_id 또는 team이 없으면 종료

    # use_day를 숫자 리스트로 변환
    use_day_list = []
    if use_day and use_day != "전체":
        use_day_list = [int(day.strip()) for day in use_day.split(",")]

    # status를 리스트로 변환
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

# 직원 정보 출력
print("\n=== 직원 정보 ===")
for idx, staff in enumerate(staffs, 1):
    print(f"Staff {idx}:")
    print(f"  Chat ID: {staff['chat_id']}")
    print(f"  Team: {staff['team']}")
    print(f"  Use Day: {staff['use_day']}")
    print(f"  Status: {staff['status']}")
print("================\n")

# 텔레그램 봇 초기화
bot = Bot(token=TELEGRAM_TOKEN)

# 예약 메뉴 대체 딕셔너리
menu_translation = {
    "컷": "C",
    "펌": "P",
    "컬러": "CL",
    "클리닉": "TM",
    "이미지 헤어 컨설팅": "컨설팅"
}

# 날짜 필터링을 위한 함수 (오늘부터 +7일, 또는 "전체")
def get_filtered_dates():
    today = datetime.today()
    return {
        0: today.strftime("%m.%d"),  # 오늘
        1: (today + timedelta(days=1)).strftime("%m.%d"),  # 내일
        2: (today + timedelta(days=2)).strftime("%m.%d"),  # 모레
        3: (today + timedelta(days=3)).strftime("%m.%d"),  # 글피
        4: (today + timedelta(days=4)).strftime("%m.%d"),  # 그글피
        5: (today + timedelta(days=5)).strftime("%m.%d"),  # 6일 후
        6: (today + timedelta(days=6)).strftime("%m.%d"),  # 7일 후
    }

# 비동기 메일 확인 및 텔레그램 알림 전송 함수
async def check_mail():
    try:
        print("Gmail IMAP 서버에 연결 중...")
        # Gmail IMAP 서버에 연결
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        print("Gmail 로그인 성공!")

        # "INBOX"로 이동
        mail.select("inbox")
        print("INBOX 폴더 선택 완료")

        # "네이버 예약 <naverbooking_noreply@navercorp.com>" 보낸 사람을 가진 메일 검색
        search_from = 'naverbooking_noreply@navercorp.com'
        print(f"메일 검색 시작: '{search_from}' 보낸 사람을 찾고 있습니다.")
        search_criteria = f'(FROM "{search_from}" UNSEEN)'  # 안 읽은 메일만 검색
        print(f"검색 조건: {search_criteria}")

        status, messages = mail.search(None, search_criteria)
        print(f"검색 상태: {status}")  # 디버깅 출력 추가

        if status == "OK":
            print(f"검색된 메일 수: {len(messages[0].split())}개")
            # 최근 메일부터 확인 (최신 메일을 먼저)
            for num in messages[0].split():
                print(f"메시지 번호: {num} 확인 중...")

                # 메일을 먼저 읽은 상태로 표시
                try:
                    mail.store(num, '+FLAGS', '\\Seen')
                except Exception as e:
                    print(f"메일을 읽은 상태로 표시하는 중 오류 발생: {e}")
                    continue  # 오류 발생 시 이 메일은 건너뛰기

                # 메일 가져오기
                status, msg_data = mail.fetch(num, "(RFC822)")

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])

                        # 제목 디코딩 (None 체크 추가)
                        subject, encoding = decode_header(msg["Subject"] or "No Subject")[0]
                        if isinstance(subject, bytes):
                            try:
                                subject = subject.decode(encoding if encoding else "utf-8")
                            except (TypeError, AttributeError):  # NoneType 오류 처리
                                subject = "No Subject"
                        print(f"메일 제목: {subject}")  # 디버깅 출력 추가

                        # "[네이버 예약]" 제목을 확인했다면
                        if "[네이버 예약]" in subject:
                            # 메일 본문 파싱
                            if msg.is_multipart():
                                for part in msg.walk():
                                    content_type = part.get_content_type()
                                    content_disposition = str(part.get("Content-Disposition"))

                                    # 본문 내용이 포함된 부분을 찾아서 (text/plain 또는 text/html)
                                    if "attachment" not in content_disposition and content_type in ["text/plain", "text/html"]:
                                        body = part.get_payload(decode=True)
                                        if body:
                                            try:
                                                # decode시 errors='replace'로 변경
                                                body = body.decode(errors="replace")  # 오류 발생 시 대체

                                                tree = html.fromstring(body)

                                                # 본문 내용에서 텍스트만 추출
                                                text_content = tree.text_content()

                                                # 예약 상태 추출
                                                reservation_status = None
                                                if "예약을 취소" in text_content:
                                                    reservation_status = "취소"
                                                elif "새로운 예약이 확정" in text_content:
                                                    reservation_status = "추가"
                                                elif "입금대기" in text_content:
                                                    reservation_status = "입금대기"

                                                # 디자이너 이름 추출
                                                designer_name = None
                                                if "실장" in text_content:
                                                    match = re.search(r"(\S+)\s*실장", text_content)
                                                    if match:
                                                        designer_name = match.group(1)  # "실장" 앞의 이름 추출
                                                elif "디자이너" in text_content:
                                                    match = re.search(r"(\S+)\s*디자이너", text_content)
                                                    if match:
                                                        designer_name = match.group(1)  # "디자이너" 앞의 이름 추출

                                                # 이용일시 추출 (정규 표현식 사용)
                                                usage_time = None
                                                match = re.search(r"\d{4}\.\d{2}\.\d{2}\.\(.*?\)\s*(오전|오후)\s*\d{1,2}:\d{2}", text_content)
                                                if match:
                                                    usage_time = match.group(0).split('.')[1:]  # "2025.05.09.(금) 오후 5:00"에서 날짜 추출
                                                    usage_time = '.'.join(usage_time)  # 05.09.(금) 오후 5:00 형식으로 변경

                                                # 예약 메뉴 추출 (정규 표현식 사용)
                                                reservation_menu = []
                                                menu_match = re.findall(r"(\S+)\s*예약금", text_content)
                                                if menu_match:
                                                    reservation_menu = menu_match  # 예약금 앞에 있는 메뉴들 추출

                                                # 메뉴 대체 (C, P, CL 등으로)
                                                reservation_menu = [menu_translation.get(menu, menu) for menu in reservation_menu]

                                                # 요청사항 추출 (HTML 테이블 구조에서 추출)
                                                request_note = None
                                                try:
                                                    # 방법 1: XPath로 "요청사항" 다음 형제 td 찾기
                                                    request_tds = tree.xpath("//td[normalize-space(text())='요청사항']")
                                                    if request_tds:
                                                        for request_td in request_tds:
                                                            # 같은 tr 내의 다음 형제 td 찾기
                                                            next_td = request_td.xpath("./following-sibling::td[1]")
                                                            if next_td:
                                                                request_note = next_td[0].text_content().strip()
                                                                print(f"요청사항 추출 성공 (XPath): {request_note[:50]}...")  # 디버깅
                                                                break
                                                    
                                                    # 요청사항 추출 후 불필요한 텍스트 제거
                                                    if request_note:
                                                        # 불필요한 텍스트 패턴들 (이것들이 나타나기 전까지 자르기)
                                                        unwanted_patterns = [
                                                            '자세히 보기',
                                                            '스마트플레이스',
                                                            '본 메일은 발신전용입니다',
                                                            '이용약관',
                                                            '운영정책',
                                                            '개인정보처리방침',
                                                            '고객센터',
                                                            'Copyright',
                                                            'NAVER Corp'
                                                        ]
                                                        for pattern in unwanted_patterns:
                                                            if pattern in request_note:
                                                                request_note = request_note.split(pattern)[0].strip()
                                                                break
                                                        # 연속된 공백이나 줄바꿈 정리
                                                        request_note = re.sub(r'\s+', ' ', request_note).strip()
                                                    
                                                    # 방법 2: XPath가 실패하면 정규표현식으로 텍스트에서 찾기
                                                    if not request_note:
                                                        # 전체 텍스트에서 "요청사항" 다음 내용 찾기
                                                        full_text = text_content
                                                        # "요청사항" 다음에 오는 텍스트 패턴 찾기 (더 유연한 패턴)
                                                        # 요청사항 다음에 공백/줄바꿈을 제외한 텍스트 찾기
                                                        match = re.search(r'요청사항\s*[:\s]*\s+([^\n\r]+(?:\s+[^\n\r]+)*)', full_text, re.MULTILINE | re.DOTALL)
                                                        if not match:
                                                            # 더 단순한 패턴 시도
                                                            match = re.search(r'요청사항\s+([^\n\r]+)', full_text)
                                                        if match:
                                                            request_note = match.group(1).strip()
                                                            # 다음 주요 섹션 전까지 자르기
                                                            next_sections = ['예약번호', '결제상태', '이용일시', '선택메뉴', '예약상품', '결제수단']
                                                            for section in next_sections:
                                                                if section in request_note:
                                                                    request_note = request_note.split(section)[0].strip()
                                                                    break
                                                            # 불필요한 텍스트 패턴들 제거
                                                            unwanted_patterns = [
                                                                '자세히 보기',
                                                                '스마트플레이스',
                                                                '본 메일은 발신전용입니다',
                                                                '이용약관',
                                                                '운영정책',
                                                                '개인정보처리방침',
                                                                '고객센터',
                                                                'Copyright',
                                                                'NAVER Corp'
                                                            ]
                                                            for pattern in unwanted_patterns:
                                                                if pattern in request_note:
                                                                    request_note = request_note.split(pattern)[0].strip()
                                                                    break
                                                            # 연속된 공백이나 줄바꿈 정리
                                                            request_note = re.sub(r'\s+', ' ', request_note).strip()
                                                            # 너무 긴 경우 잘라내기
                                                            if len(request_note) > 500:
                                                                request_note = request_note[:500].strip()
                                                            print(f"요청사항 추출 성공 (정규표현식): {request_note[:50]}...")  # 디버깅
                                                    
                                                    if not request_note:
                                                        print("요청사항을 찾을 수 없습니다.")  # 디버깅
                                                        # 디버깅: "요청사항" 텍스트가 있는지 확인
                                                        if "요청사항" in text_content:
                                                            print("'요청사항' 텍스트는 발견되었지만 추출 실패")
                                                            # 요청사항 주변 텍스트 출력 (디버깅용)
                                                            idx = text_content.find("요청사항")
                                                            if idx >= 0:
                                                                debug_text = text_content[max(0, idx-50):idx+200]
                                                                print(f"요청사항 주변 텍스트: {debug_text}")
                                                except Exception as e:
                                                    print(f"요청사항 추출 중 오류 발생: {e}")
                                                    traceback.print_exc()

                                                # 텔레그램 메시지 준비
                                                message = ""
                                                if designer_name:
                                                    message += f"{designer_name} / "
                                                if usage_time:
                                                    message += f"{usage_time} "
                                                if reservation_menu:
                                                    message += f"{' '.join(reservation_menu)} "
                                                if reservation_status:
                                                    message += f"{reservation_status} 되었습니다."
                                                if request_note:
                                                    message += f"\n\n요청사항: {request_note}"
                                                    print(f"요청사항이 메시지에 추가됨: {request_note[:30]}...")  # 디버깅
                                                else:
                                                    print("요청사항이 없어 메시지에 추가되지 않음")  # 디버깅

                                                # 예약 상태나 디자이너 이름, 이용일시, 예약 메뉴가 있으면 텔레그램으로 전송
                                                if message:
                                                    print(f"새 예약 알림: {message}")  # 디버깅 출력 추가
                                                    # 필터링 로직 추가
                                                    filtered_dates = get_filtered_dates()
                                                    
                                                    for staff in staffs:
                                                        # 조건 1: 디자이너 이름 필터링
                                                        if staff["team"] != "전체" and staff["team"] != designer_name:
                                                            print(f"디자이너 불일치: {staff['team']} != {designer_name} (전체가 아닌 경우에만 체크)")
                                                            continue  # 디자이너가 일치하지 않으면 이 직원은 스킵

                                                        # 조건 2: use_day 필터링 (전체/당일)
                                                        if staff["use_day"] != "전체":
                                                            # 날짜 문자열에서 월.일 부분만 추출 (예: "05.10.(토) 오후 1:30" -> "05.10")
                                                            date_part = usage_time.split()[0]
                                                            if not any(filtered_dates[day] in date_part for day in staff["use_day"]):
                                                                print(f"날짜 불일치: {staff['use_day']} != {date_part} (전체가 아닌 경우에만 체크)")
                                                                continue  # 조건에 맞지 않으면 이 직원은 스킵

                                                        # 조건 3: status 필터링 (예: 입금대기, 추가, 취소)
                                                        if staff["status"] != "전체" and reservation_status not in staff["status"]:
                                                            print(f"상태 불일치: {staff['status']} != {reservation_status} (전체가 아닌 경우에만 체크)")
                                                            continue  # 상태가 일치하지 않으면 이 직원은 스킵

                                                        # 모든 조건이 맞다면 메시지 전송
                                                        await bot.send_message(chat_id=staff["chat_id"], text=message)
                                                        print(f"메시지 전송 완료: {message} (수신자: {staff['team']})")
                                                break  # 본문 파트 하나만 처리하고 break로 탈출
                                            except Exception as e:
                                                print(f"메일 본문 처리 중 오류 발생: {e}")
                                        else:
                                            print("본문을 가져올 수 없습니다. 본문이 비어있을 수 있습니다.")

            # 연결 종료
            try:
                mail.close()
                mail.logout()
            except Exception as e:
                print(f"메일 연결 종료 중 오류 발생: {e}")

    except Exception as e:
        print(f"메일 확인 중 오류 발생: {e}")

# 비동기 메일 확인 함수 호출
async def main():
    while True:
        await check_mail()
        time.sleep(10)  # 10초마다 확인

if __name__ == "__main__":
    asyncio.run(main())
