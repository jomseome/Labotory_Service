import calendar
import hashlib
from datetime import datetime, date, timedelta
from html import escape

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


def reservation_identity(reservation):
    """Return a stable identity for a sheet row without exposing it in the UI."""
    return tuple(str(reservation.get(header, '') or '') for header in HEADERS)


def find_reservation_row(worksheet, reservation):
    target_identity = reservation_identity(reservation)
    for row_index, record in enumerate(worksheet.get_all_records(), start=2):
        if reservation_identity(record) == target_identity:
            return row_index
    return None


def update_reservation(
    worksheet,
    original_reservation,
    reservation_date,
    reservation_time,
    reserver,
    purpose,
):
    row_index = find_reservation_row(worksheet, original_reservation)
    if row_index is None:
        return False

    created_at = original_reservation.get('생성일시') or datetime.now().strftime(
        '%Y-%m-%d %H:%M:%S'
    )
    worksheet.update(
        range_name=f'A{row_index}:E{row_index}',
        values=[[
            reservation_date,
            reservation_time,
            reserver,
            purpose,
            created_at,
        ]],
    )
    return True


def delete_reservation(worksheet, reservation):
    row_index = find_reservation_row(worksheet, reservation)
    if row_index is not None:
        worksheet.delete_rows(row_index)
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
            created_dt = datetime.fromisoformat(str(created_at))
        except ValueError:
            try:
                created_dt = datetime.strptime(str(created_at), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue

        if now - created_dt >= timedelta(days=30):
            rows_to_delete.append(idx)

    for row_index in reversed(rows_to_delete):
        worksheet.delete_rows(row_index)

    return len(rows_to_delete)


def init_session_state():
    today = date.today()
    defaults = {
        'current_year': today.year,
        'current_month': today.month,
        'selected_date': None,
        'editing_reservation_key': None,
        'status_message': '',
        'last_refresh': datetime.now(),
        'reservation_table_version': 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_table_selection():
    st.session_state.reservation_table_version += 1


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
    st.session_state.editing_reservation_key = None
    clear_table_selection()


def go_to_today():
    today = date.today()
    st.session_state.current_year = today.year
    st.session_state.current_month = today.month
    st.session_state.selected_date = today.isoformat()
    st.session_state.editing_reservation_key = None
    clear_table_selection()


def select_calendar_date(date_key):
    st.session_state.selected_date = date_key
    st.session_state.editing_reservation_key = None
    clear_table_selection()


def format_date(year, month, day):
    return f'{year:04d}-{month:02d}-{day:02d}'


def reservation_sort_key(item):
    reservation_time = str(item.get('시간') or '').strip()
    start_time_text = reservation_time.split('-')[0].strip()

    for time_format in ('%H:%M', '%H:%M:%S'):
        try:
            parsed_time = datetime.strptime(start_time_text, time_format).time()
            return (0, parsed_time, reservation_time, item.get('예약자명', ''))
        except ValueError:
            continue

    return (1, reservation_time, item.get('예약자명', ''))


def sort_reservations(reservations):
    return sorted(
        reservations,
        key=lambda item: (
            str(item.get('날짜', '')),
            reservation_sort_key(item),
            str(item.get('생성일시', '')),
        ),
    )


def inject_styles():
    st.markdown(
        """
        <style>
        :root {
            --ink: #172033;
            --muted: #667085;
            --line: #e5eaf2;
            --primary: #6d5dfc;
            --sunday: #ef476f;
            --saturday: #3478f6;
        }
        .stApp {
            background:
                radial-gradient(circle at 8% 2%, rgba(109,93,252,.10), transparent 28rem),
                radial-gradient(circle at 92% 18%, rgba(38,198,218,.10), transparent 24rem),
                #f7f8fc;
        }
        .block-container { max-width: 1500px; padding-top: 2rem; padding-bottom: 4rem; }
        .app-hero {
            position: relative;
            overflow: hidden;
            padding: 2rem 2.2rem;
            margin-bottom: 1.2rem;
            border: 1px solid rgba(255,255,255,.65);
            border-radius: 24px;
            color: white;
            background: linear-gradient(120deg, #5146e5 0%, #7767ff 52%, #26b9c7 100%);
            box-shadow: 0 22px 55px rgba(75,66,190,.23);
        }
        .app-hero::after {
            content: '';
            position: absolute;
            width: 260px;
            height: 260px;
            right: -65px;
            top: -125px;
            border: 42px solid rgba(255,255,255,.10);
            border-radius: 50%;
        }
        .hero-eyebrow { font-size: .72rem; font-weight: 800; letter-spacing: .16em; opacity: .78; }
        .app-hero h1 {
            margin: .4rem 0 .35rem;
            color: white;
            font-size: clamp(1.8rem, 3vw, 2.8rem);
            letter-spacing: -.04em;
        }
        .app-hero p { margin: 0; color: rgba(255,255,255,.82); font-size: .98rem; }
        .metric-card {
            padding: 1rem 1.15rem;
            margin-bottom: .8rem;
            border: 1px solid var(--line);
            border-radius: 16px;
            background: rgba(255,255,255,.92);
            box-shadow: 0 8px 24px rgba(23,32,51,.055);
        }
        .metric-label { color: var(--muted); font-size: .76rem; font-weight: 700; }
        .metric-value { margin-top: .25rem; color: var(--ink); font-size: 1.55rem; font-weight: 800; }
        .section-title {
            margin: 1.25rem 0 .65rem;
            color: var(--ink);
            font-size: 1.15rem;
            font-weight: 800;
            letter-spacing: -.02em;
        }
        .calendar-title {
            padding: .35rem 0;
            color: var(--ink);
            font-size: 1.45rem;
            font-weight: 850;
            text-align: center;
            letter-spacing: -.03em;
        }
        .weekday {
            padding: .65rem 0;
            margin-bottom: .15rem;
            border-radius: 12px;
            color: #475467;
            background: #eef1f7;
            font-size: .78rem;
            font-weight: 800;
            text-align: center;
        }
        .weekday.sunday { color: var(--sunday); background: #fff0f3; }
        .weekday.saturday { color: var(--saturday); background: #edf4ff; }
        .calendar-day-marker { display: none; }
        [data-testid="stColumn"]:has(.calendar-day-marker) {
            min-height: 138px;
            padding: .45rem .5rem;
            border: 1px solid var(--line);
            border-radius: 14px;
            background: rgba(255,255,255,.86);
            box-shadow: 0 3px 12px rgba(23,32,51,.035);
            transition: transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease;
        }
        [data-testid="stColumn"]:has(.calendar-day-marker):hover {
            z-index: 2;
            transform: translateY(-2px);
            border-color: #cfd5e4;
            box-shadow: 0 10px 24px rgba(23,32,51,.09);
        }
        [data-testid="stColumn"]:has(.calendar-empty) {
            border-color: transparent;
            background: rgba(238,241,247,.34);
            box-shadow: none;
        }
        [data-testid="stColumn"]:has(.calendar-selected) {
            border-color: #8174ff;
            background: #f3f1ff;
            box-shadow: 0 0 0 2px rgba(109,93,252,.13);
        }
        [data-testid="stColumn"]:has(.calendar-day-marker) .stButton > button {
            min-height: 2.1rem;
            padding: .15rem .45rem;
            border: 0;
            background: transparent;
            box-shadow: none;
            justify-content: flex-start;
        }
        [data-testid="stColumn"]:has(.calendar-day-marker) .stButton > button:hover {
            color: var(--primary);
            background: rgba(109,93,252,.08);
        }
        [data-testid="stColumn"]:has(.calendar-day-marker) .stButton p {
            color: var(--ink);
            font-size: .95rem;
            font-weight: 850;
        }
        [data-testid="stColumn"]:has(.calendar-sunday) .stButton p { color: var(--sunday); }
        [data-testid="stColumn"]:has(.calendar-saturday) .stButton p { color: var(--saturday); }
        .reservation-chip {
            overflow: hidden;
            padding: .28rem .45rem;
            margin: .2rem 0;
            border-left: 3px solid #7767ff;
            border-radius: 5px 8px 8px 5px;
            color: #4b5565;
            background: #f5f3ff;
            font-size: .72rem;
            line-height: 1.25;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .reservation-stack { max-height: 80px; overflow-y: auto; padding-right: .15rem; }
        [data-testid="stDataFrame"] {
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 16px;
            box-shadow: 0 8px 24px rgba(23,32,51,.05);
        }
        section[data-testid="stSidebar"] {
            border-right: 1px solid #e6e8f0;
            background: rgba(251,251,254,.97);
        }
        .sidebar-brand {
            padding: 1.1rem 0 .8rem;
            color: var(--ink);
            font-size: 1.2rem;
            font-weight: 850;
            letter-spacing: -.03em;
        }
        .sidebar-hint {
            padding: .85rem .95rem;
            border: 1px solid #e2defe;
            border-radius: 12px;
            color: #5c50c9;
            background: #f4f2ff;
            font-size: .83rem;
            line-height: 1.45;
        }
        @media (max-width: 900px) {
            [data-testid="stColumn"]:has(.calendar-day-marker) { min-height: 105px; padding: .25rem; }
            .reservation-chip { font-size: .65rem; }
            .app-hero { padding: 1.5rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_summary(reservations):
    today_key = date.today().isoformat()
    month_prefix = f'{st.session_state.current_year:04d}-{st.session_state.current_month:02d}'
    today_count = sum(
        1 for item in reservations if str(item.get('날짜', '')) == today_key
    )
    month_count = sum(
        1
        for item in reservations
        if str(item.get('날짜', '')).startswith(month_prefix)
    )

    columns = st.columns(3)
    metrics = [
        ('오늘 예약', f'{today_count}건'),
        ('이번 달 예약', f'{month_count}건'),
        ('전체 예약', f'{len(reservations)}건'),
    ]
    for column, (label, value) in zip(columns, metrics):
        column.markdown(
            '<div class="metric-card">'
            f'<div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div>'
            '</div>',
            unsafe_allow_html=True,
        )


def render_calendar(reservations):
    year = st.session_state.current_year
    month = st.session_state.current_month

    st.markdown('<div class="section-title">월간 캘린더</div>', unsafe_allow_html=True)
    previous, title, today_column, next_column = st.columns([1.2, 5, 1.1, 1.2])
    previous.button(
        '← 이전 달', on_click=change_month, args=(-1,), use_container_width=True
    )
    title.markdown(
        f'<div class="calendar-title">{year}년 {month}월</div>',
        unsafe_allow_html=True,
    )
    today_column.button('오늘', on_click=go_to_today, use_container_width=True)
    next_column.button(
        '다음 달 →', on_click=change_month, args=(1,), use_container_width=True
    )

    week_days = [
        ('일', 'sunday'), ('월', ''), ('화', ''), ('수', ''),
        ('목', ''), ('금', ''), ('토', 'saturday'),
    ]
    week_header = st.columns(7, gap='small')
    for column, (day_name, class_name) in zip(week_header, week_days):
        column.markdown(
            f'<div class="weekday {class_name}">{day_name}</div>',
            unsafe_allow_html=True,
        )

    month_days = calendar.Calendar(firstweekday=calendar.SUNDAY).monthdayscalendar(
        year, month
    )
    for week in month_days:
        columns = st.columns(7, gap='small')
        for weekday_index, (column, day_number) in enumerate(zip(columns, week)):
            if day_number == 0:
                column.markdown(
                    '<span class="calendar-day-marker calendar-empty"></span>',
                    unsafe_allow_html=True,
                )
                continue

            date_key = format_date(year, month, day_number)
            day_reservations = sorted(
                [
                    item for item in reservations
                    if str(item.get('날짜', '')) == date_key
                ],
                key=reservation_sort_key,
            )
            marker_classes = ['calendar-day-marker']
            if weekday_index == 0:
                marker_classes.append('calendar-sunday')
            elif weekday_index == 6:
                marker_classes.append('calendar-saturday')
            if st.session_state.selected_date == date_key:
                marker_classes.append('calendar-selected')

            column.markdown(
                f'<span class="{" ".join(marker_classes)}"></span>',
                unsafe_allow_html=True,
            )
            reservation_count = f' · {len(day_reservations)}건' if day_reservations else ''
            column.button(
                f'{day_number}{reservation_count}',
                key=f'day-{date_key}',
                on_click=select_calendar_date,
                args=(date_key,),
                use_container_width=True,
            )

            if day_reservations:
                chips = ''.join(
                    '<div class="reservation-chip" title="'
                    f'{escape(str(item.get("예약 목적", "")))}">'
                    f'<strong>{escape(str(item.get("시간", "")))}</strong> '
                    f'{escape(str(item.get("예약자명", "")))}'
                    '</div>'
                    for item in day_reservations
                )
                column.markdown(
                    f'<div class="reservation-stack">{chips}</div>',
                    unsafe_allow_html=True,
                )


def resolve_editing_reservation(reservations):
    editing_key = st.session_state.editing_reservation_key
    if editing_key is None:
        return None
    return next(
        (
            item for item in reservations
            if reservation_identity(item) == tuple(editing_key)
        ),
        None,
    )


def render_reservation_table(reservations):
    st.markdown('<div class="section-title">전체 예약 목록</div>', unsafe_allow_html=True)
    st.caption('예약 행을 클릭하면 왼쪽 사이드바에서 내용을 수정할 수 있습니다.')
    if not reservations:
        st.info('등록된 예약이 없습니다. 달력에서 날짜를 선택해 첫 예약을 추가해보세요.')
        return

    table_rows = [
        {
            '날짜': str(item.get('날짜', '')),
            '시간': str(item.get('시간', '')),
            '예약자명': str(item.get('예약자명', '')),
            '예약 목적': str(item.get('예약 목적', '')),
            '생성일시': str(item.get('생성일시', '')),
        }
        for item in reservations
    ]
    table_event = st.dataframe(
        table_rows,
        key=f'reservation-table-{st.session_state.reservation_table_version}',
        width='stretch',
        height=min(470, 48 + len(table_rows) * 36),
        hide_index=True,
        row_height=36,
        on_select='rerun',
        selection_mode='single-row',
        column_config={
            '날짜': st.column_config.TextColumn('날짜', width='small'),
            '시간': st.column_config.TextColumn('시간', width='small'),
            '예약자명': st.column_config.TextColumn('예약자명', width='small'),
            '예약 목적': st.column_config.TextColumn('예약 목적', width='large'),
            '생성일시': st.column_config.TextColumn('생성일시', width='medium'),
        },
    )
    selected_rows = table_event.selection.rows
    if selected_rows:
        selected_index = selected_rows[0]
        if 0 <= selected_index < len(reservations):
            selected_item = reservations[selected_index]
            st.session_state.editing_reservation_key = reservation_identity(selected_item)
            st.session_state.selected_date = str(selected_item.get('날짜', ''))


def safe_date(date_text):
    try:
        return date.fromisoformat(str(date_text))
    except ValueError:
        return date.today()


def reset_editor():
    st.session_state.editing_reservation_key = None
    clear_table_selection()


def reservation_sidebar(worksheet, reservations):
    st.sidebar.markdown('<div class="sidebar-brand">예약 관리</div>', unsafe_allow_html=True)
    editing_item = resolve_editing_reservation(reservations)

    if st.session_state.editing_reservation_key is not None and editing_item is None:
        st.sidebar.warning('선택한 예약을 찾을 수 없습니다. 목록을 새로고침해 주세요.')
        reset_editor()

    if editing_item is not None:
        st.sidebar.markdown('### 예약 정보 수정')
        st.sidebar.caption('선택한 예약의 내용을 변경한 뒤 저장하세요.')
        identity_digest = hashlib.sha1(
            '|'.join(reservation_identity(editing_item)).encode('utf-8')
        ).hexdigest()[:10]

        with st.sidebar.form(f'edit-reservation-{identity_digest}'):
            edited_date = st.date_input(
                '예약 날짜', value=safe_date(editing_item.get('날짜', ''))
            )
            edited_time = st.text_input('시간', value=str(editing_item.get('시간', '')))
            edited_reserver = st.text_input(
                '예약자명', value=str(editing_item.get('예약자명', ''))
            )
            edited_purpose = st.text_area(
                '예약 목적', value=str(editing_item.get('예약 목적', ''))
            )
            save_column, cancel_column = st.columns(2)
            save_changes = save_column.form_submit_button(
                '저장', type='primary', use_container_width=True
            )
            cancel_edit = cancel_column.form_submit_button('취소', use_container_width=True)

        if cancel_edit:
            reset_editor()
            st.rerun()

        if save_changes:
            fields = [edited_time, edited_reserver, edited_purpose]
            if any(not value.strip() for value in fields):
                st.sidebar.error('날짜, 시간, 예약자명, 예약 목적을 모두 입력해 주세요.')
            elif update_reservation(
                worksheet,
                editing_item,
                edited_date.isoformat(),
                edited_time.strip(),
                edited_reserver.strip(),
                edited_purpose.strip(),
            ):
                st.session_state.selected_date = edited_date.isoformat()
                st.session_state.status_message = '예약 정보가 수정되었습니다.'
                reset_editor()
                st.rerun()
            else:
                st.sidebar.error(
                    '예약을 찾을 수 없어 수정하지 못했습니다. 새로고침 후 다시 시도해 주세요.'
                )

        with st.sidebar.expander('예약 삭제'):
            st.warning('삭제한 예약은 복구할 수 없습니다.')
            if st.button(
                '이 예약을 삭제합니다',
                key=f'delete-{identity_digest}',
                use_container_width=True,
            ):
                if delete_reservation(worksheet, editing_item):
                    st.session_state.status_message = '예약이 삭제되었습니다.'
                    reset_editor()
                    st.rerun()
                else:
                    st.error('이미 삭제되었거나 예약을 찾을 수 없습니다.')
        return

    selected_date = st.session_state.selected_date
    if selected_date is None:
        st.sidebar.markdown(
            '<div class="sidebar-hint">달력에서 날짜를 선택하면 새 예약을 등록할 수 있습니다.'
            '<br><br>기존 예약은 표에서 행을 클릭해 수정하세요.</div>',
            unsafe_allow_html=True,
        )
        return

    selected_count = sum(
        1 for item in reservations if str(item.get('날짜', '')) == selected_date
    )
    st.sidebar.markdown(f'### {selected_date}')
    st.sidebar.caption(f'현재 {selected_count}건의 예약이 있습니다.')
    with st.sidebar.form('new-reservation', clear_on_submit=True):
        reservation_time = st.text_input('시간', value='09:00 - 10:00')
        reserver = st.text_input('예약자명')
        purpose = st.text_area('예약 목적')
        save_reservation = st.form_submit_button(
            '새 예약 저장', type='primary', use_container_width=True
        )

    if save_reservation:
        fields = [reservation_time, reserver, purpose]
        if any(not value.strip() for value in fields):
            st.sidebar.error('시간, 예약자명, 예약 목적을 모두 입력해 주세요.')
        else:
            add_reservation(
                worksheet,
                selected_date,
                reservation_time.strip(),
                reserver.strip(),
                purpose.strip(),
            )
            st.session_state.status_message = f'{selected_date} 예약이 저장되었습니다.'
            clear_table_selection()
            st.rerun()


def main():
    st.set_page_config(
        page_title='연구실 회의실 예약 시스템',
        page_icon='📅',
        layout='wide',
    )
    init_session_state()
    inject_styles()

    try:
        worksheet = get_google_sheet()
    except Exception as exc:
        st.error('Google Sheets 인증 또는 연결에 문제가 발생했습니다.')
        st.error(str(exc))
        return

    deleted_count = delete_old_reservations(worksheet)
    if deleted_count > 0:
        st.session_state.status_message = f'30일 이상 지난 예약 {deleted_count}건을 정리했습니다.'

    reservations = sort_reservations(fetch_reservations(worksheet))
    st.markdown(
        """
        <div class="app-hero">
            <div class="hero-eyebrow">LAB MEETING ROOM</div>
            <h1>회의실 예약 캘린더</h1>
            <p>한눈에 일정을 확인하고, 빠르게 예약을 등록하거나 수정하세요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    action_column, _ = st.columns([1.2, 7])
    if action_column.button('↻ 새로고침', use_container_width=True):
        st.session_state.last_refresh = datetime.now()
        clear_table_selection()
        st.rerun()

    if st.session_state.status_message:
        st.success(st.session_state.status_message)
        st.session_state.status_message = ''

    render_summary(reservations)
    render_calendar(reservations)
    render_reservation_table(reservations)
    reservation_sidebar(worksheet, reservations)


if __name__ == '__main__':
    main()
