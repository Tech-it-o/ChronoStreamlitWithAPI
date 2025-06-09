import streamlit as st
from datetime import datetime, timedelta
import pytz
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests
import torch
import json
import re
import ast
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

st.set_page_config(page_title="ChronoCall-Q", page_icon="🗓️")

st.markdown("""
    <style>
    /* เปลี่ยนกรอบหลักให้เป็นสีม่วง */
    div[data-baseweb="input"] > div {
        border: 2px solid #a020f0 !important;
        border-radius: 6px;
        padding: 2px;
        box-shadow: none !important;
    }

    /* ตอน focus แล้ว */
    div[data-baseweb="input"] > div:focus-within {
        border: 2px solid #a020f0 !important;
        box-shadow: 0 0 0 2px rgba(160, 32, 240, 0.3) !important;
    }

    /* input ด้านในไม่ให้แสดงเงาสีแดงเลย */
    input {
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
    }

    /* ลบพวกกรอบแดงที่แอบซ่อนอยู่ */
    .css-1cpxqw2, .css-1d391kg, .css-1y4p8pa {
        border: 2px solid #a020f0 !important;
        box-shadow: none !important;
    }

    /* force กล่อง input ให้ไม่ใช้สีแดงแม้จะ error */
    div:has(input:focus) {
        border-color: #a020f0 !important;
    }

    /* เปลี่ยนสีข้อความหัวข้อเป็นม่วงเมื่อ hover */
    details:hover > summary {
        color: #9D00FF !important;
        font-weight: bold;
    }

    /* เปลี่ยนสี caret ^ (ไอคอนสามเหลี่ยม) ตอน hover */
    details:hover summary::-webkit-details-marker {
        color: #9D00FF !important;
    }
    </style>
""", unsafe_allow_html=True)


# --- Model ---

def convert_to_dict(text):
    match = re.search(r"<tool_call>\n(.*?)\n</tool_call>", text)

    if match:
        tool_dict_str = match.group(1)
        try:
            result = ast.literal_eval(tool_dict_str)
            return(result)
        except Exception as e:
            return({})
    else:
        return({})

# --- API ---

API_URL = "https://06cc-2403-6200-89a8-e79b-6052-f6a9-a0e4-e75d.ngrok-free.app/generate"

def get_model_answer(messages):
    try:
        response = requests.post(API_URL, json={"messages": messages})
        if response.status_code == 200:
            return response.json().get("response", "❌ ไม่พบ response จาก API")
        else:
            return f"❌ API error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"❌ Request failed: {str(e)}"

# --- Calendar ---

SCOPES = ['https://www.googleapis.com/auth/calendar']

with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        b64_data = base64.b64encode(img_file.read()).decode()
    return b64_data

def create_flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id": st.secrets["client_id"],
                "client_secret": st.secrets["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [st.secrets["redirect_uri"]],
            }
        },
        scopes=SCOPES,
        redirect_uri=st.secrets["redirect_uri"]
    )

def generate_auth_url(flow):
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
    return auth_url

def create_service(creds):
    return build("calendar", "v3", credentials=creds)

# --- Adding ---

def extract_time_or_dash(iso_time: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_time)

        if "T" in iso_time:
            return dt.strftime("%H:%M")
        else:
            return "-"
    except ValueError:
        return "-"

def handle_calendar_action(service, action_data):
    name = action_data.get("name")
    args = action_data.get("arguments", {})
    
    if name == "add_event_date":
        date_str = args["date"]
        time_str = args["time"]
        title = args["title"]

        dt_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        dt_end = dt_start + timedelta(hours=1)

        event = {
            'summary': title,
            'start': {
                'dateTime': dt_start.isoformat(),
                'timeZone': 'Asia/Bangkok',
            },
            'end': {
                'dateTime': dt_end.isoformat(),
                'timeZone': 'Asia/Bangkok',
            },
        }

        created = service.events().insert(calendarId='primary', body=event).execute()
        st.success(f"✅ เพิ่มกิจกรรม: {title} [ดูใน Calendar]({created.get('htmlLink')})")

    elif name == "delete_event_date":
        date_str = args["date"]
        title = args["title"]
        events = get_events_by_date_and_title(service, date_str, title)
        if events:
            for event in events:
                service.events().delete(calendarId='primary', eventId=event['id']).execute()
            st.success(f"🗑 ลบนัด: {title} ในวันที่ {date_str} แล้ว")
        else:
            st.warning(f"ไม่พบนัด: {title} ในวันที่ {date_str}")

    elif name == "update_event":
        date_str = args["date"]
        new_time_str = args["time"]
        title = args["title"]
        events = get_events_by_date_and_title(service, date_str, title)

        if events:
            for event in events:
                new_start = datetime.strptime(f"{date_str} {new_time_str}", "%Y-%m-%d %H:%M")
                new_end = new_start + timedelta(hours=1)
                event["start"]["dateTime"] = new_start.isoformat()
                event["end"]["dateTime"] = new_end.isoformat()
                service.events().update(calendarId='primary', eventId=event["id"], body=event).execute()
            st.success(f"✏️ เปลี่ยนเวลานัด: {title} เป็น {new_time_str}")
        else:
            st.warning(f"ไม่พบนัด: {title} ในวันที่ {date_str}")

    elif name == "view_event_date":
        date_str = args["date"]
        events = get_events_by_date(service, date_str)
        if not events:
            st.info("ไม่มีนัดในวันนี้")
        else:
            st.write(f"📅 นัดทั้งหมดในวันที่ {date_str}:")
            for e in events:
                date = e['start'].get('dateTime', e['start'].get('date'))
                time = extract_time_or_dash(date)
                st.write(f"- {e['summary']} เวลา: {time}")

def get_events_by_date(service, date_str):
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    start = date_obj.strftime("%Y-%m-%dT00:00:00Z")
    end = (date_obj + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    
    # # DEBUG
    # st.write(f"Fetching events for date: {date_str}")
    # st.write(f"timeMin = {start}, timeMax = {end}")

    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    
    except HttpError as error:
        st.error(f"❌ Google Calendar API error: {error}")
        return []

    except Exception as e:
        st.error(f"❌ Unknown error: {e}")
        return []

def get_events_by_date_and_title(service, date_str, title):
    events = get_events_by_date(service, date_str)
    return [e for e in events if e.get("summary") == title]

# --- Email ---

sender = st.secrets["email"]["sender"]
receiver = st.secrets["email"]["receiver"]
password = st.secrets["email"]["password"]

def send_email(user_email):
    subject = "New Beta Tester - ChronoCall-Q"
    body = f"""\
    มีผู้สนใจเข้าร่วม Beta Test
    อีเมล: {user_email}
    """

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        return True
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")
        return False

# --- Streamlit ---

def main():

    # ดึง query params
    params = st.query_params
    code = params.get("code", None)

    # ถ้ายังไม่ได้ login
    if "credentials" not in st.session_state:
        if code:
            flow = create_flow()
            try:
                flow.fetch_token(code=code)
                creds = flow.credentials
                st.session_state["credentials"] = {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": creds.scopes
                }
                st.success("🎉 ล็อกอินสำเร็จ! พร้อมใช้งานแล้ว")
                st.rerun()
            except Exception as e:
                st.error(f"เกิดข้อผิดพลาด: {e}")
                return
        else:
            flow = create_flow()
            auth_url = generate_auth_url(flow)

            # --- Title + Login ---

            st.markdown(f"""
                <!-- ชื่อ -->
                <div class="fade-in-title custom-title">ChronoCall-Q</div>

                <!-- คำอธิบาย -->
                <div class="fade-in-subtitle">
                    Intelligent Calendar Command Parser
                </div>

                <!-- เครดิต -->
                <div class="fade-in-credit">
                    By TechitoTamani | wayward-wolves
                </div>

                <!-- ปุ่ม -->
                <div class="fade-in-button login-button" style="margin-top: 30px; text-align: center;">
                    <a href="{auth_url}" target="_blank" rel="noopener noreferrer">
                        <button>Login with Google</button>
                    </a>
                </div>
            """, unsafe_allow_html=True)

            # --- Emali sender ---

            st.markdown("""
            <div class="fade-in-up">
                <p>ถ้า <strong>Login ไม่ได้ใช่ไหม?</strong><br>ไม่เป็นไร! ส่งคำขอเข้าร่วม Beta Test มาให้เราก่อนได้เลย</p>
            </div>
            """, unsafe_allow_html=True)

            email = st.text_input("กรอกอีเมลของคุณที่นี่")

            if st.button("ส่งคำขอเข้าร่วม Beta Test"):
                if email:
                    if send_email(email):
                        st.success("ส่งคำขอเรียบร้อยแล้ว!")
                    else:
                        st.error("เกิดข้อผิดพลาดในการส่ง กรุณาลองใหม่อีกครั้ง")
                else:
                    st.warning("กรุณากรอกอีเมลก่อนกดส่ง")

            # --- pic ---

            img_b64 = get_base64_image("IMG_1358.jpg")

            st.markdown(f'''
                <img src="data:image/jpeg;base64,{img_b64}" class="fade-in-image">
            ''', unsafe_allow_html=True)

            st.stop()

    # Logged in
    creds = Credentials(**st.session_state["credentials"])
    service = create_service(creds)

    st.title("ChronoCall-Q")
    st.caption("วิธีใช้งาน")

    with st.expander("การเพิ่มเหตุการณ์ (Add Event)"):
        st.markdown("""
    เพื่อเพิ่มเหตุการณ์ใหม่ ต้องระบุ:
    - **ชื่อเหตุการณ์**
    - **วันที่**
    - **เวลา**

    > **ตัวอย่าง:** เพิ่มนัดประชุมพรุ่งนี้ตอนสิบโมง
    """)

    with st.expander("การลบเหตุการณ์ (Delete Event)"):
        st.markdown("""
    เพื่อทำการลบเหตุการณ์ ต้องระบุ:
    - **ชื่อเหตุการณ์**
    - **วันที่**

    > **ตัวอย่าง:** เพิ่มนัดประชุมพรุ่งนี้ตอนสิบโมง
    """)

    with st.expander("การอัปเดตเหตุการณ์ (Update Event)"):
        st.markdown("""
    เพื่อเปลี่ยนเวลาเหตุการณ์ในวันเดียวกัน ต้องระบุ:
    - **ชื่อเหตุการณ์**
    - **วันที่**
    - **เวลาใหม่**

    > **ตัวอย่าง:** เปลี่ยนนัดประชุมพรุ่งนี้เป็นสิบเอ็ดโมง
    """)

    with st.expander("การดูเหตุการณ์ (View Events)"):
        st.markdown("""
    เพื่อดูรายการเหตุการณ์ในวันใดวันหนึ่ง ต้องระบุ:
    - **วันที่ที่ต้องการดู**

    > **ตัวอย่าง:** พรุ่งนี้มีนัดอะไรบ้าง
    """)

    if "user_input" not in st.session_state:
        st.session_state.user_input = ""
        

    user_input = st.text_input("พิมพ์คำสั่งที่นี่ แล้วกด Enter หรือกดปุ่มยืนยัน", value=st.session_state.user_input, key="input")

    submit_button = st.button("ยืนยัน")

    if (user_input and user_input != st.session_state.user_input) or submit_button:

        bangkok_tz = pytz.timezone("Asia/Bangkok")
        now = datetime.now(bangkok_tz)
        current_date = now.strftime("%Y-%m-%d")
        current_day = now.strftime("%A")

        messages = [
            {
                "role": "system",
                "content": f"You are Qwen, created by Alibaba Cloud. You are a helpful assistant.\n\nCurrent Date: {current_date}.\n\nCurrent Day: {current_day}."
            },
            {
                "role": "user",
                "content": user_input
            }
        ]

        with st.spinner("โมเดลกำลังคิด..."):
            response = get_model_answer(messages)

        st.success(f"Chrono: {response}")
        func_call_dict = convert_to_dict(response)
        handle_calendar_action(service, func_call_dict)

        st.session_state.user_input = ""

if __name__ == "__main__":
    main()