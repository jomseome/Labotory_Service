import calendar
from datetime import datetime, date, timedelta

import gspread
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials

SERVICE_ACCOUNT_FILE = 'service_account.json'
SPREADSHEET_ID = '1hfxurpOIVmgskJ4TgEdpPSf4Up8eQyBPy378RpvuyN8'
WORKSHEET_NAME = '시트1'
HEADERS = ['날짜', '시간', '예약자명', '예약 목적', '생성일시']


def get_google_sheet():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    try:
        import json
        service_account_json = st.secrets.get("SERVICE_ACCOUNT_JSON")
        if service_account_json:
            service_account_info = json.loads(service_account_json)
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(
                service_account_info, scope
            )
        else:
            service_account_info = st.secrets["service_account"]
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(
                service_account_info, scope
            )
    except (KeyError, FileNotFoundError):
        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            SERVICE_ACCOUNT_FILE, scope
        )
    
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

    try:
        first_row = worksheet.row_values(1)
        if first_row != HEADERS:
            worksheet.insert_row(HEADERS, index=1)
    except gspread.exceptions.APIError:
        worksheet.insert_row(HEADERS, index=1)

    return worksheet


def fetch_reservations(worksheet):
    records = worksheet.get_all_records()
    return records


def add_reservation(worksheet, reservation_date, reservation_time, reserver, purpose):
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    worksheet.append_row([
        reservation_date,
        reservation_time,
        reserver,
        purpose,
        created_at,
    ])


def delete_reservation(worksheet, reservation_date, reservation_time, reserver):
    records = worksheet.get_all_records()
    for idx, record in enumerate(records, start=2):
        if (record.get('날짜') == reservation_date and 
            record.get('시간') == reservation_time and 
            record.get('예약자명') == reserver):
            worksheet.delete_rows(idx)
            return True
    return False


def delete_old_reservations(worksheet):
    records = worksheet.get_all_records()
    now = datetime.now()
    rows_to_delete = []

    for idx, record in enumerate(records, start=2):
        created_at = record.get('생성일시')
        if not created_at:
            continue
        try:
            created_dt = datetime.fromisoformat(created_at)
        except ValueError:
            try:
                created_dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue

        if now - created_dt >= timedelta(days=30):
            rows_to_delete.append(idx)

    for row_index in reversed(rows_to_delete):
        worksheet.delete_rows(row_index)

    return len(rows_to_delete)


def init_session_state():
    if 'current_year' not in st.session_state:
        today = date.today()
        st.session_state.current_year = today.year
        st.session_state.current_month = today.month
        st.session_state.selected_date = None
        st.session_state.selected_reservation_index = None
        st.session_state.status_message = ''
        st.session_state.last_refresh = datetime.now()


def change_month(offset):
    year = st.session_state.current_year
    month = st.session_state.current_month + offset
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1

    st.session_state.current_year = year
    st.session_state.current_month = month
    st.session_state.selected_date = None
    st.session_state.selected_reservation_index = None


def format_date(year, month, day):
    return f'{year:04d}-{month:02d}-{day:02d}'


def render_calendar(reservations):
    year = st.session_state.current_year
    month = st.session_state.current_month
    month_name = calendar.month_name[month]

    st.markdown(f'# {year}년 {month_name}')
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if st.button('◀ 이전 달'):
            change_month(-1)
    with col2:
        st.write(' ')
    with col3:
        if st.button('다음 달 ▶'):
            change_month(1)

    week_days = ['월', '화', '수', '목', '금', '토', '일']
    week_header = st.columns(7)
    for idx, day_name in enumerate(week_days):
        week_header[idx].markdown(f'**{day_name}**')

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(year, month)

    for week in month_days:
        cols = st.columns(7)
        for idx, day in enumerate(week):
            if day == 0:
                cols[idx].write(' ')
                continue

            date_key = format_date(year, month, day)
            day_reservations = [r for r in reservations if r.get('날짜') == date_key]
            label = f'{day}'
            if day_reservations:
                label += f' ({len(day_reservations)})'

            if cols[idx].button(label, key=f'day-{date_key}'):
                st.session_state.selected_date = date_key
                st.session_state.selected_reservation_index = None

            if day_reservations:
                for item in day_reservations[:2]:
                    cols[idx].caption(
                        f"{item.get('시간','')} {item.get('예약자명','')}"
                    )


def reservation_sidebar(worksheet, reservations):
    st.sidebar.header('예약 입력')
    if st.session_state.selected_date is None:
        st.sidebar.info('달력에서 날짜를 선택하세요.')
        return

    selected = st.session_state.selected_date
    st.sidebar.markdown(f'### {selected} 예약 등록')

    reservation_time = st.sidebar.text_input('시간', value='09:00 - 10:00')
    reserver = st.sidebar.text_input('예약자명')
    purpose = st.sidebar.text_area('예약 목적')

    if st.sidebar.button('저장'):
        if not reserver.strip() or not purpose.strip() or not reservation_time.strip():
            st.sidebar.error('모든 항목을 입력해주세요.')
        else:
            add_reservation(
                worksheet,
                selected,
                reservation_time.strip(),
                reserver.strip(),
                purpose.strip(),
            )
            st.session_state.status_message = f'{selected} 예약이 저장되었습니다.'
            st.session_state.selected_reservation_index = None
            st.experimental_rerun()

    st.sidebar.write('---')
    today_reservations = [r for r in reservations if r.get('날짜') == selected]
    if today_reservations:
        st.sidebar.subheader('선택한 날짜 예약 목록')
        option_labels = [
            f"{i + 1}. {item.get('시간')} | {item.get('예약자명')}"
            for i, item in enumerate(today_reservations)
        ]
        selected_index = st.session_state.selected_reservation_index
        if selected_index is None or selected_index >= len(option_labels):
            selected_index = 0

        selected_index = st.sidebar.radio(
            '예약 선택',
            list(range(len(option_labels))),
            index=selected_index,
            format_func=lambda i: option_labels[i],
        )
        st.session_state.selected_reservation_index = selected_index

        selected_item = today_reservations[selected_index]
        st.sidebar.markdown('### 예약 상세')
        st.sidebar.write(f"- 시간: {selected_item.get('시간')}")
        st.sidebar.write(f"- 예약자: {selected_item.get('예약자명')}")
        st.sidebar.write(f"- 목적: {selected_item.get('예약 목적')}")
        st.sidebar.write(f"- 생성일시: {selected_item.get('생성일시')}")
        
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.sidebar.button('삭제', key=f'delete-{selected_index}'):
                delete_reservation(
                    worksheet,
                    selected_item.get('날짜'),
                    selected_item.get('시간'),
                    selected_item.get('예약자명')
                )
                st.session_state.status_message = '예약이 삭제되었습니다.'
                st.session_state.selected_reservation_index = None
                st.experimental_rerun()
    else:
        st.sidebar.info('해당 날짜에 등록된 예약이 없습니다.')


def main():
    st.set_page_config(page_title='연구실 회의실 예약 시스템', layout='wide')
    init_session_state()

    try:
        worksheet = get_google_sheet()
    except Exception as exc:
        st.error('Google Sheets 인증 또는 연결에 문제가 발생했습니다.')
        st.error(str(exc))
        return

    deleted_count = delete_old_reservations(worksheet)
    if deleted_count > 0:
        st.success(f'30일 이상 지난 예약 {deleted_count}건을 삭제했습니다.')

    col1, col2, col3 = st.columns([1, 1, 5])
    with col1:
        if st.button('🔄 새로고침'):
            st.session_state.last_refresh = datetime.now()
            st.rerun()
    
    reservations = fetch_reservations(worksheet)

    render_calendar(reservations)
    reservation_sidebar(worksheet, reservations)

    if st.session_state.status_message:
        st.success(st.session_state.status_message)

    st.write('---')
    st.subheader('전체 예약 목록')
    if reservations:
        for item in reservations:
            st.write(
                f"• {item.get('날짜')} {item.get('시간')} | {item.get('예약자명')} | {item.get('예약 목적')} | 생성일시: {item.get('생성일시')}"
            )
    else:
        st.info('예약 데이터가 없습니다.')


if __name__ == '__main__':
    main()
