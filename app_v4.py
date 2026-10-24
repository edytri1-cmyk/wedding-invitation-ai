from dotenv import load_dotenv
load_dotenv()

import midtransclient
import uuid
import os
import json
import time
import base64
import urllib.parse
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from jinja2 import Template
from google import genai
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials

# File JSON Database Lokal
RSVP_FILE = "rsvp_data.json"
ORDERS_FILE = "orders_data.json"
CHAT_FILE = "chat_messages.json"
STATS_FILE = "stats_visitors.json"
INVITATION_DATA_FILE = "generated_invitation.json"

def load_json(filename, default_val):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_val
    return default_val

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_visitor():
    """Mencatat statistik pengunjung harian"""
    stats = load_json(STATS_FILE, {})
    today_str = datetime.now().strftime("%Y-%m-%d")
    stats[today_str] = stats.get(today_str, 0) + 1
    save_json(STATS_FILE, stats)

# Catat kunjungan saat app dimuat
log_visitor()

def file_to_base64(uploaded_file):
    if uploaded_file is not None:
        bytes_data = uploaded_file.getvalue()
        base64_encoded = base64.b64encode(bytes_data).decode('utf-8')
        mime_type = uploaded_file.type
        return f"data:{mime_type};base64,{base64_encoded}"
    return None

def generate_ai_content(prompt, theme_choice, groom_name, bride_name):
    GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
    GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

    if not GEMINI_KEY and "api_keys" in st.secrets and "GEMINI_API_KEY" in st.secrets["api_keys"]:
        GEMINI_KEY = st.secrets["api_keys"]["GEMINI_API_KEY"]
    elif not GEMINI_KEY and "GEMINI_API_KEY" in st.secrets:
        GEMINI_KEY = st.secrets["GEMINI_API_KEY"]

    if not GROQ_KEY and "api_keys" in st.secrets and "GROQ_API_KEY" in st.secrets["api_keys"]:
        GROQ_KEY = st.secrets["api_keys"]["GROQ_API_KEY"]
    elif not GROQ_KEY and "GROQ_API_KEY" in st.secrets:
        GROQ_KEY = st.secrets["GROQ_API_KEY"]

    if GEMINI_KEY and len(GEMINI_KEY) > 10:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                gemini_client = genai.Client(api_key=GEMINI_KEY)
                response = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                if response and response.text:
                    clean_res = response.text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(clean_res)
                    return data, "Google Gemini"
            except Exception as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(1.5 * (attempt + 1))
                else:
                    break

    if GROQ_KEY and len(GROQ_KEY) > 10:
        groq_models = ["openai/gpt-oss-20b", "llama-3.1-8b-instant", "llama-3.3-70b-versatile"]
        try:
            groq_client = Groq(api_key=GROQ_KEY)
            for m_id in groq_models:
                try:
                    completion = groq_client.chat.completions.create(
                        model=m_id,
                        messages=[
                            {"role": "system", "content": "You are a JSON generator. Output ONLY a valid JSON object matching the requested schema."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"}
                    )
                    res_text = completion.choices[0].message.content
                    return json.loads(res_text), f"Groq ({m_id})"
                except Exception as e:
                    continue
        except Exception as e:
            pass

    default_data = {
        "quote": f"Dua hati, satu cinta, menyatu dalam janji suci pernikahan {groom_name} & {bride_name}.",
        "theme_bg": "bg-slate-900",
        "theme_card_bg": "bg-slate-800",
        "theme_text": "text-amber-100"
    }
    return default_data, "Default Static Fallback"

# ==========================================
# INISIALISASI KONEKSI GOOGLE SHEETS
# ==========================================
@st.cache_resource
def init_google_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # Memuat kredensial dari Streamlit Secrets
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    # Menghubungkan ke file Google Sheets 'WeddingInvitationOrders'
    sheet = client.open("WeddingInvitationOrders").sheet1
    return sheet

def load_orders_from_gsheets():
    try:
        sheet = init_google_sheet()
        records = sheet.get_all_records()
        orders_db = {}
        for row in records:
            order_id = str(row.get("order_id", ""))
            if order_id:
                orders_db[order_id] = {
                    "token": str(row.get("token", "")),
                    "status": str(row.get("status", "")),
                    "user_id": str(row.get("user_id", ""))
                }
        return orders_db
    except Exception as e:
        st.error(f"Gagal terhubung ke Google Sheets: {e}")
        return {}

def save_order_to_gsheets(order_id, token, status, user_id):
    """Fungsi untuk menyimpan atau memperbarui data pesanan ke Google Sheets"""
    try:
        sheet = init_google_sheet()
        # Cari apakah order_id sudah ada di sheet
        cell = sheet.find(str(order_id))
        if cell:
            # Update baris yang sudah ada
            row_num = cell.row
            sheet.update_cell(row_num, 2, str(token))   # Kolom B: token
            sheet.update_cell(row_num, 3, str(status))  # Kolom C: status
            sheet.update_cell(row_num, 4, str(user_id)) # Kolom D: user_id
        else:
            # Tambah baris baru di paling bawah
            sheet.append_row([str(order_id), str(token), str(status), str(user_id)])
        return True
    except Exception as e:
        st.error(f"Gagal menyimpan ke Google Sheets: {e}")
        return False

# ==========================================
# 1. PENANGKAP TOKEN URL VIA GOOGLE SHEETS
# ==========================================
query_params = st.query_params
url_token = query_params.get("token", None)

if url_token and st.session_state.get("user_token") != url_token:
    orders_db = load_orders_from_gsheets()
    
    token_found = False
    clean_url_token = str(url_token).strip()
    
    for order_id, data in orders_db.items():
        if isinstance(data, dict):
            stored_token = str(data.get("token", "")).strip()
            stored_status = str(data.get("status", "")).strip().upper()
            
            # Cocokkan token dengan database Google Sheets
            if stored_token == clean_url_token and stored_status in ["ACTIVATED", "ACTIVE", "PAID"]:
                # 1. Ambil user_id asli pembuat undangan dari Google Sheets (Kolom D)
                stored_user_id = str(data.get("user_id", "")).strip()
                real_user_id = stored_user_id if stored_user_id else order_id
                
                # 2. Pulihkan sesi pengguna menggunakan user_id asli dari sessionId
                st.session_state["user_id"] = real_user_id
                st.session_state["current_user"] = real_user_id
                
                st.session_state["activated_code_input"] = order_id
                st.session_state["user_token"] = url_token
                
                st.session_state["is_session_active"] = True  
                st.session_state["agreed_terms"] = True       
                st.session_state["design_ready"] = True       
                
                # Arahkan langsung ke Tahap 3
                st.session_state["active_step"] = "3️⃣ Buat Link Undangan ➡️"
                token_found = True
                break
                
    if token_found:
        st.success("✅ Sesi berhasil dipulihkan melalui Google Sheets!")
        st.rerun()
    else:
        st.warning(f"⚠️ Token URL tidak valid atau kedaluwarsa. (Token dibaca: {clean_url_token[:8]}...)")


# ---------------------------------------------------------
# PENGATURAN UTAMA & PEMILIHAN MODE (CLIENT VS ADMIN)
# ---------------------------------------------------------
st.set_page_config(page_title="Wedding Invitation", layout="wide")

# Inisialisasi Unique User ID per Session Streamlit
if "user_id" not in st.session_state:
    st.session_state["user_id"] = f"user_{str(uuid.uuid4())[:8]}"

current_user = st.session_state["user_id"]
    
# =========================================================
# DETEKSI PENGIRIMAN RSVP ATAU URL TAMU UNDANGAN
# =========================================================
query_params = st.query_params

rsvp_action = query_params.get("rsvp_action", None)
if rsvp_action == "true":
    incoming_name = query_params.get("nama", "Tamu Anonim")
    incoming_status = query_params.get("status", "Hadir")
    incoming_ucapan = query_params.get("ucapan", "-")
    target_user_id = query_params.get("user_id", current_user)
    
    # Load database RSVP yang ada
    rsvp_list = load_json(RSVP_FILE, [])
    
    new_entry = {
        "User_ID": target_user_id,
        "Nama Tamu": urllib.parse.unquote(incoming_name),
        "Kehadiran": urllib.parse.unquote(incoming_status),
        "Ucapan & Doa": urllib.parse.unquote(incoming_ucapan),
        "Waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Tambahkan ke list
    rsvp_list.append(new_entry)
    
    # Simpan permanen ke rsvp_data.json
    save_json(RSVP_FILE, rsvp_list)

guest_name = query_params.get("to", None)
if guest_name:
    saved_invitation = load_json(INVITATION_DATA_FILE, {})
    if saved_invitation and "rendered_html" in saved_invitation:
        html_template = saved_invitation["rendered_html"]
        final_html = html_template.replace("Budi Sudarsono", guest_name)
        st.components.v1.html(final_html, height=1200, scrolling=True)
    else:
        st.markdown("### 💍 Undangan Pernikahan")
        st.warning("⚠️ Undangan belum di-generate oleh pemilik acara.")
    st.stop()

st.sidebar.title("🛠️ Navigasi Sistem")
st.sidebar.markdown(f"🆔 **ID Sesi Anda:** `{current_user}`")
app_mode = st.sidebar.radio("Pilih Mode Aplikasi:", ["💍 User (Wedding Invitation AI)", "🔑 Admin"])

# =========================================================
# KONDISI 1: DASHBOARD ADMIN
# =========================================================
if app_mode == "🔑 Admin":
    st.title("🔑 Dashboard Admin & Pemantauan Owner")
    
    admin_pass = st.sidebar.text_input("Password Admin:", type="password")
    if admin_pass != "owner123": 
        st.warning("⚠️ Silakan masukkan password admin di sidebar untuk mengakses dashboard.")
        st.stop()

    st.sidebar.success("✅ Login Admin Berhasil")

    admin_menu = st.sidebar.radio(
        "Pilih Menu Admin:", 
        [
            "💳 Dashboard Pendapatan", 
            "🔑 Aktivasi & Override Manual", 
            "📊 Statistik & Tren Kunjungan", 
            "💬 Live Helpdesk Chat"
        ]
    )

    # 1. Dashboard Pendapatan
    if admin_menu == "💳 Dashboard Pendapatan":
        st.subheader("💳 Dashboard Rekap & Monitoring Pendapatan")
        st.info("Memantau total transaksi sukses dan akumulasi pendapatan dari lisensi undangan digital.")

        orders_data = load_json(ORDERS_FILE, {})
        if not orders_data:
            st.warning("Belum ada data pesanan atau transaksi yang tercatat.")
        else:
            order_list = []
            for code, info in orders_data.items():
                order_list.append({
                    "Order ID / Kode": code,
                    "Nama Pemilik": info.get("name", "Tidak Diketahui"),
                    "Status": info.get("status", "UNKNOWN"),
                    "Waktu Aktivasi": info.get("activated_at", "-")
                })
            
            df_orders = pd.DataFrame(order_list)
            total_orders = len(df_orders)
            total_activated = len(df_orders[df_orders["Status"] == "ACTIVATED"])
            estimated_revenue = total_activated * 49000
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Transaksi Tercatat", total_orders)
            col2.metric("Lisensi Aktif", total_activated)
            col3.metric("Estimasi Pendapatan", f"Rp {estimated_revenue:,.0f}".replace(",", "."))
            
            st.markdown("---")
            st.markdown("### 📋 Daftar Detail Transaksi & Lisensi")
            st.dataframe(df_orders, use_container_width=True, hide_index=True)

    # 2. Aktivasi & Override Manual
    elif admin_menu == "🔑 Aktivasi & Override Manual":
        st.subheader("🔑 Fitur Override & Aktivasi Manual Darurat")
        st.info("Gunakan menu ini untuk memberikan atau memperpanjang akses lisensi secara manual kepada klien jika terjadi kendala pembayaran.")

        with st.form("manual_override_form"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                manual_code = st.text_input("Kode Unik / Order ID (contoh: WAI-INV-12345)")
                client_name = st.text_input("Nama Klien / Mempelai", "Klien VIP")
            with col_f2:
                client_email = st.text_input("Email Klien", "klien@example.com")
                override_status = st.selectbox("Status Lisensi", ["ACTIVATED", "EXPIRED", "PENDING"])
                
            submitted_override = st.form_submit_button("🚀 Simpan / Override Aktivasi", type="primary")
            
            if submitted_override:
                if manual_code.strip():
                    orders_data = load_json(ORDERS_FILE, {})
                    orders_data[manual_code.strip()] = {
                        "name": client_name,
                        "email": client_email,
                        "status": override_status,
                        "activated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    save_json(ORDERS_FILE, orders_data)
                    st.success(f"✅ Berhasil meng-override lisensi untuk Order ID: **{manual_code.strip()}** dengan status **{override_status}**!")
                    st.rerun()
                else:
                    st.error("⚠️ Masukkan Kode Unik / Order ID yang valid.")

        st.markdown("---")
        st.markdown("### 📋 Kelola / Cabut Akses Lisensi")
        orders_data = load_json(ORDERS_FILE, {})
        if orders_data:
            selected_code_to_delete = st.selectbox("Pilih Order ID untuk Dihapus/Direvoke:", ["-- Pilih --"] + list(orders_data.keys()))
            if selected_code_to_delete != "-- Pilih --":
                if st.button("🗑️ Revoke / Hapus Akses Lisensi Ini", type="secondary"):
                    del orders_data[selected_code_to_delete]
                    save_json(ORDERS_FILE, orders_data)
                    st.success(f"Akses untuk {selected_code_to_delete} berhasil dicabut.")
                    st.rerun()

# 3. Statistik & Tren Kunjungan
    elif admin_menu == "📊 Statistik & Tren Kunjungan":
        st.subheader("📊 Statistik Pengunjung & Tren Kunjungan")
        st.info("Memantau jumlah kunjungan ke aplikasi undangan digital secara harian, mingguan, bulanan, dan kumulatif.")
        
        stats_data = load_json(STATS_FILE, {})
        if not stats_data:
            st.info("Belum ada data kunjungan tercatat.")
        else:
            # Konversi data JSON (format: {"YYYY-MM-DD": count}) ke DataFrame Pandas
            df_stats = pd.DataFrame(list(stats_data.items()), columns=["Tanggal", "Jumlah Pengunjung"])
            df_stats["Tanggal"] = pd.to_datetime(df_stats["Tanggal"])
            df_stats = df_stats.sort_values(by="Tanggal", ascending=False)
            
            # 1. Total Akumulasi Keseluruhan
            total_visitors = df_stats["Jumlah Pengunjung"].sum()
            
            # 2. Kunjungan Hari Ini
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_visitors = stats_data.get(today_str, 0)
            
            # 3. Kunjungan Minggu Ini (7 hari terakhir dari hari ini)
            now_dt = datetime.now()
            start_of_week = now_dt - pd.Timedelta(days=7)
            mask_weekly = (df_stats["Tanggal"] >= pd.to_datetime(start_of_week.strftime("%Y-%m-%d"))) & (df_stats["Tanggal"] <= pd.to_datetime(today_str))
            weekly_visitors = df_stats.loc[mask_weekly, "Jumlah Pengunjung"].sum()
            
            # 4. Kunjungan Bulan Ini (Bulan & Tahun berjalan)
            current_month_str = now_dt.strftime("%Y-%m")
            mask_monthly = df_stats["Tanggal"].dt.strftime("%Y-%m") == current_month_str
            monthly_visitors = df_stats.loc[mask_monthly, "Jumlah Pengunjung"].sum()
            
            # Tampilkan dalam 4 kolom Metrik
            col_s1, col_s2, col_s3, col_s4 = st.columns(4)
            col_s1.metric("Hari Ini", f"{today_visitors} Orang")
            col_s2.metric("Minggu Ini", f"{weekly_visitors} Orang")
            col_s3.metric("Bulan Ini", f"{monthly_visitors} Orang")
            col_s4.metric("Akumulasi Total", f"{total_visitors} Orang")
            
            st.markdown("---")
            
            # Tampilkan Grafik Tren (diurutkan kembali secara kronologis untuk grafik)
            st.markdown("### 📈 Grafik Tren Pengunjung Harian")
            df_chart = df_stats.sort_values(by="Tanggal", ascending=True).copy()
            df_chart["Tanggal"] = df_chart["Tanggal"].dt.strftime("%Y-%m-%d")
            st.bar_chart(df_chart.set_index("Tanggal"))
            
            st.markdown("---")
            st.markdown("### 📋 Rincian Data Harian")
            # Ubah format tanggal kembali ke string untuk ditampilkan di tabel
            df_stats["Tanggal"] = df_stats["Tanggal"].dt.strftime("%Y-%m-%d")
            st.dataframe(df_stats, use_container_width=True, hide_index=True)

    # 4. Live Helpdesk Chat (Admin Reply)
    elif admin_menu == "💬 Live Helpdesk Chat":
        st.subheader("💬 Live Chat Helpdesk dengan Pengguna (Privat per Sesi)")
        
        chat_history = load_json(CHAT_FILE, [])
        if not chat_history:
            st.info("Belum ada pesan chat masuk dari pengguna manapun.")
        else:
            active_sessions = list(set([c.get("session_id", "Unknown") for c in chat_history]))
            selected_session = st.selectbox("Pilih Pengguna / Sesi:", active_sessions)
            
            st.markdown(f"--- \n**Sedang membalas chat untuk Sesi:** `{selected_session}`")
            session_chats = [c for c in chat_history if c.get("session_id") == selected_session]
            
            @st.fragment(run_every=3)
            def render_admin_selected_chat():
                chat_container = st.container(height=350)
                with chat_container:
                    for chat in session_chats:
                        sender_label = f"👤 **User ({selected_session})**" if chat['sender'] == "User" else "🛠️ **Admin**"
                        st.markdown(f"{sender_label} *({chat['time']})*:\n{chat['message']}")
                        st.markdown("---")
            
            render_admin_selected_chat()
            
            admin_reply = st.text_input(f"Balas Pesan ke {selected_session}:", key=f"reply_{selected_session}")
            if st.button("Kirim Balasan ke User Ini", key=f"btn_reply_{selected_session}"):
                if admin_reply.strip():
                    chat_history.append({
                        "session_id": selected_session,
                        "sender": "Admin",
                        "message": admin_reply,
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    save_json(CHAT_FILE, chat_history)
                    st.success("Balasan terkirim ke user!")
                    st.rerun()

# =========================================================
# KONDISI 2: KLIEN (WEDDING GENERATOR)
# =========================================================
else:
    st.markdown("""
    <h3 style='color: #db2777; font-size: 22px; font-weight: bold; margin-bottom: 0px;'>
        💍 Wedding AI Invitation Generator
    </h3>
""", unsafe_allow_html=True)

    if "agreed_terms" not in st.session_state:
        st.session_state["agreed_terms"] = False

    # Inisialisasi state untuk alur navigasi aktif jika belum ada
    if "active_step_idx" not in st.session_state:
        st.session_state["active_step_idx"] = 0

    is_session_active = st.session_state.get("is_session_active", False)

    # Styling CSS Kustom untuk Kartu Alur Navigasi ala Gambar 2
    st.markdown("""
        <style>
        .step-nav-card {
            background: #ffffff;
            border: 2px solid #fda4af;
            border-radius: 16px;
            padding: 15px 10px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(225, 29, 72, 0.08);
            margin-bottom: 10px;
        }
        .step-circle {
            background: #be123c;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 14px;
            margin-bottom: 8px;
            box-shadow: 0 2px 6px rgba(190, 18, 60, 0.3);
        }
        .step-title {
            color: #881337;
            font-weight: bold;
            font-size: 13px;
            margin-bottom: 4px;
        }
        .step-desc {
            color: #78716c;
            font-size: 10px;
            line-height: 1.3;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("🧭 **Alur Aplikasi:**")

    # Daftar tahapan alur beserta deskripsinya
    steps_info = [
        {"num": "1", "title": "Panduan Aplikasi", "desc": "Baca ketentuan & setujui syarat."},
        {"num": "2", "title": "Desain & Preview", "desc": "Isi data mempelai, foto & tema."},
        {"num": "3", "title": "Buat Link Undangan", "desc": "Aktivasi & bayar langganan."},
        {"num": "4", "title": "Manajemen RSVP", "desc": "Pantau kehadiran & ucapan tamu."}
    ]

    # Jika sesi aktif, batasi hanya 2 tahap terakhir
    if is_session_active:
        active_cols = st.columns(2)
        subset_steps = steps_info[2:]
        indices = [2, 3]
    else:
        active_cols = st.columns(4)
        subset_steps = steps_info
        indices = [0, 1, 2, 3]

    # Render menu alur berbentuk kartu interaktif
    for idx, col in enumerate(active_cols):
        real_idx = indices[idx]
        info = subset_steps[idx]
        
        with col:
            # Tampilan visual kartu
            st.markdown(f"""
                <div class="step-nav-card" style="border-color: {'#be123c' if st.session_state['active_step_idx'] == real_idx else '#fda4af'};">
                    <div class="step-circle">{info['num']}</div>
                    <div class="step-title">{info['title']}</div>
                    <div class="step-desc">{info['desc']}</div>
                </div>
            """, unsafe_allow_html=True)
            
            # Tombol pilih menu
            btn_label = f"Pilih Tahap {info['num']}"
            if st.button(btn_label, key=f"nav_btn_{real_idx}", use_container_width=True):
                st.session_state["active_step_idx"] = real_idx
                st.rerun()

    #st.markdown("---")

    # Tentukan string active_step agar kompatibel dengan logika kode di bawahnya
    full_menu_list = [
        "1️⃣ Panduan Aplikasi ➡️",
        "2️⃣ Desain & Preview Undangan ➡️",
        "3️⃣ Buat Link Undangan ➡️",
        "4️⃣ Manajemen RSVP Tamu"
    ]
    if is_session_active:
        menu_steps_mapping = full_menu_list[2:]
    else:
        menu_steps_mapping = full_menu_list

    active_step = menu_steps_mapping[st.session_state["active_step_idx"] if not is_session_active else (st.session_state["active_step_idx"] - 2)]

    # =========================================================
    # 2. PENCOCOKAN KONTEN BERDASARKAN KATA KUNCI (Tanpa Indeks)
    # =========================================================
    
    if "Panduan Aplikasi" in active_step:
        # Style CSS Kustom - Soft Pink Sakura Japanese Theme
        st.markdown("""
            <style>
            .landing-wrapper::before {
                content: "🌸";
                position: absolute;
                font-size: 120px;
                opacity: 0.06;
                top: -20px;
                right: 20px;
                transform: rotate(15deg);
            }
            .hero-title {
                color: #9f1239;
                font-family: 'Playfair Display', serif;
                font-size: 36px;
                font-weight: 700;
                line-height: 1.25;
                margin-bottom: 14px;
            }
            .hero-desc {
                color: #9f1239;
                font-size: 15px;
                line-height: 1.65;
                margin-bottom: 22px;
                opacity: 0.9;
            }
            .feature-box-pink {
                background: rgba(255, 255, 255, 0.75);
                backdrop-filter: blur(8px);
                color: #4c0519;
                padding: 18px 16px;
                border-radius: 16px;
                border: 1px solid #fda4af;
                box-shadow: 0 6px 18px rgba(190, 18, 60, 0.08);
                height: 100%;
                transition: all 0.3s ease;
            }
            .feature-box-pink:hover {
                transform: translateY(-5px);
                background: #fff;
                box-shadow: 0 12px 24px rgba(190, 18, 60, 0.12);
            }
            .step-card-pink {
                background: rgba(255, 255, 255, 0.8);
                backdrop-filter: blur(6px);
                color: #4c0519;
                padding: 20px 14px;
                border-radius: 16px;
                border: 1px solid #fda4af;
                text-align: center;
                box-shadow: 0 6px 16px rgba(190, 18, 60, 0.07);
                height: 100%;
            }
            .section-heading {
                text-align: center;
                color: #9f1239;
                font-family: 'Playfair Display', serif;
                font-size: 24px;
                font-weight: 600;
                margin: 32px 0 18px 0;
                letter-spacing: 0.3px;
            }
            .security-box {
                background: linear-gradient(135deg, #be123c 0%, #9f1239 100%);
                color: #fff;
                padding: 22px 24px;
                border-radius: 16px;
                border: 1px solid #e11d48;
                margin-top: 24px;
                box-shadow: 0 8px 20px rgba(136, 19, 55, 0.18);
            }
            </style>
        """, unsafe_allow_html=True)
    
        # Buka wrapper utama landing page
        st.markdown('<div class="landing-wrapper">', unsafe_allow_html=True)
    
        # 1. HERO SECTION
        hero_col1, hero_col2 = st.columns([1.35, 1])
        
        with hero_col1:
            st.markdown("""
                <div style="padding-top: 10px;">
                    <span style="background: #ffe4e6; color: #9f1239; padding: 6px 16px; border-radius: 30px; font-size: 12px; font-weight: 600; letter-spacing: 0.8px;">
                        🌸 Wedding Invitation Online • Nuansa Sakura
                    </span>
                    <h1 class="hero-title" style="margin-top: 18px;">
                        Undang Tamu Anda dengan Keindahan & Kemudahan
                    </h1>
                    <p class="hero-desc">
                        Buat undangan pernikahan digital yang elegan, berkesan, dan mudah dibagikan. 
                        Inspirasi Jepang dengan nuansa bunga sakura yang lembut & mewah untuk hari spesial Anda.
                    </p>
                </div>
            """, unsafe_allow_html=True)
            
            btn_c1, btn_c2 = st.columns(2)
            with btn_c1:
                if st.button("🌸 Buat Undangan Sekarang", type="primary", use_container_width=True):
                    st.session_state["agreed_terms"] = True
                    st.rerun()
            with btn_c2:
                st.button("▶ Lihat Demo", use_container_width=True)
    
        with hero_col2:
            st.markdown("""
                <div style="border-radius: 20px; overflow: hidden; border: 3px solid #fda4af; box-shadow: 0 14px 32px rgba(190, 18, 60, 0.15);">
                    <img src="https://images.unsplash.com/photo-1522673607200-164d1b6ce486?auto=format&fit=crop&w=800&q=80" 
                         style="width: 100%; height: 310px; object-fit: cover;">
                </div>
            """, unsafe_allow_html=True)
    
        st.markdown("<br>", unsafe_allow_html=True)
    
        # 2. TENTANG APLIKASI
        st.markdown('<h2 class="section-heading">🌸 Tentang Aplikasi</h2>', unsafe_allow_html=True)
        st.markdown("""
            <p style="text-align: center; color: #9f1239; font-size: 14.5px; line-height: 1.7; max-width: 780px; margin: 0 auto 10px auto;">
                EternalVow membantu pasangan menciptakan undangan pernikahan digital yang indah, modern, 
                dan berkesan. Tanpa perlu coding, tanpa ribet — fokus saja pada cinta kalian. 
                Desain terinspirasi keindahan sakura Jepang yang lembut dan elegan.
            </p>
        """, unsafe_allow_html=True)
    
        # 3. FITUR UTAMA
        st.markdown('<h2 class="section-heading">✨ Fitur Aplikasi</h2>', unsafe_allow_html=True)
        
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            st.markdown("""
                <div class="feature-box-pink">
                    <h4 style="color: #be123c; font-size: 15px; margin-bottom: 6px;">🎨 Custom Design Templates</h4>
                    <p style="font-size: 12.5px; color: #9f1239; margin: 0;">Pilihan tema eksklusif bernuansa sakura, blush gold & klasik mewah yang bisa dikustomisasi.</p>
                </div>
            """, unsafe_allow_html=True)
        with f_col2:
            st.markdown("""
                <div class="feature-box-pink">
                    <h4 style="color: #be123c; font-size: 15px; margin-bottom: 6px;">💌 RSVP Real-time</h4>
                    <p style="font-size: 12.5px; color: #9f1239; margin: 0;">Konfirmasi kehadiran tamu secara real-time dengan dashboard yang mudah dipantau.</p>
                </div>
            """, unsafe_allow_html=True)
        with f_col3:
            st.markdown("""
                <div class="feature-box-pink">
                    <h4 style="color: #be123c; font-size: 15px; margin-bottom: 6px;">🎵 Music & Animation</h4>
                    <p style="font-size: 12.5px; color: #9f1239; margin: 0;">Tambahkan musik romantis dan animasi kelopak sakura yang lembut.</p>
                </div>
            """, unsafe_allow_html=True)
    
        st.markdown("<div style='height: 12px'></div>", unsafe_allow_html=True)
    
        f_col4, f_col5, f_col6 = st.columns(3)
        with f_col4:
            st.markdown("""
                <div class="feature-box-pink">
                    <h4 style="color: #be123c; font-size: 15px; margin-bottom: 6px;">📖 Guest Book</h4>
                    <p style="font-size: 12.5px; color: #9f1239; margin: 0;">Tamu dapat meninggalkan ucapan & doa terbaik untuk kalian berdua.</p>
                </div>
            """, unsafe_allow_html=True)
        with f_col5:
            st.markdown("""
                <div class="feature-box-pink">
                    <h4 style="color: #be123c; font-size: 15px; margin-bottom: 6px;">🖼️ Photo Gallery</h4>
                    <p style="font-size: 12.5px; color: #9f1239; margin: 0;">Galeri foto interaktif untuk kenangan spesial hari bahagia kalian.</p>
                </div>
            """, unsafe_allow_html=True)
        with f_col6:
            st.markdown("""
                <div class="feature-box-pink">
                    <h4 style="color: #be123c; font-size: 15px; margin-bottom: 6px;">🌐 Multi-language</h4>
                    <p style="font-size: 12.5px; color: #9f1239; margin: 0;">Dukungan Bahasa Indonesia & English untuk tamu internasional.</p>
                </div>
            """, unsafe_allow_html=True)
    
        # 4. CARA PENGGUNAAN
        st.markdown('<h2 class="section-heading">📖 Cara Penggunaan</h2>', unsafe_allow_html=True)
        
        s_col1, s_col2, s_col3, s_col4 = st.columns(4)
        with s_col1:
            st.markdown("""
                <div class="step-card-pink">
                    <div style="background: #be123c; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px auto; font-size: 13px; font-weight: bold;">1</div>
                    <h5 style="color: #9f1239; font-size: 14px; margin: 0 0 6px 0;">Pilih Template</h5>
                    <p style="font-size: 12px; color: #be123c; margin: 0; opacity: 0.9;">Pilih desain sakura yang paling kalian sukai.</p>
                </div>
            """, unsafe_allow_html=True)
        with s_col2:
            st.markdown("""
                <div class="step-card-pink">
                    <div style="background: #be123c; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px auto; font-size: 13px; font-weight: bold;">2</div>
                    <h5 style="color: #9f1239; font-size: 14px; margin: 0 0 6px 0;">Isi Data</h5>
                    <p style="font-size: 12px; color: #be123c; margin: 0; opacity: 0.9;">Masukkan data pengantin, acara & detail penting.</p>
                </div>
            """, unsafe_allow_html=True)
        with s_col3:
            st.markdown("""
                <div class="step-card-pink">
                    <div style="background: #be123c; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px auto; font-size: 13px; font-weight: bold;">3</div>
                    <h5 style="color: #9f1239; font-size: 14px; margin: 0 0 6px 0;">Personalisasi</h5>
                    <p style="font-size: 12px; color: #be123c; margin: 0; opacity: 0.9;">Sesuaikan musik, foto, dan animasi sakura.</p>
                </div>
            """, unsafe_allow_html=True)
        with s_col4:
            st.markdown("""
                <div class="step-card-pink">
                    <div style="background: #be123c; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px auto; font-size: 13px; font-weight: bold;">4</div>
                    <h5 style="color: #9f1239; font-size: 14px; margin: 0 0 6px 0;">Bagikan Link</h5>
                    <p style="font-size: 12px; color: #be123c; margin: 0; opacity: 0.9;">Sebar via WhatsApp, Instagram, atau email.</p>
                </div>
            """, unsafe_allow_html=True)
    
        # 5. JAMINAN KEAMANAN
        st.markdown("""
            <div class="security-box">
                <h4 style="color: #fef08a; font-size: 16px; margin-bottom: 10px;">🔒 Jaminan Keamanan & Data Privacy</h4>
                <p style="font-size: 13px; color: #ffe4e6; margin-bottom: 0; line-height: 1.6;">
                    Seluruh data pribadi, informasi acara, dan daftar kontak tamu Anda dilindungi dengan enkripsi tingkat tinggi (SSL). 
                    Kami menjamin kerahasiaan data sesuai standar internasional. Anda memiliki kendali penuh untuk memperbarui atau menghapus data kapan saja.
                </p>
            </div>
        """, unsafe_allow_html=True)
    
        # Tutup wrapper
        st.markdown('</div>', unsafe_allow_html=True)
    
        st.markdown("---")
        
        # Checkbox Persetujuan
        agreement = st.checkbox(
            "Saya telah membaca dan menyetujui syarat serta kebijakan keamanan data platform.", 
            value=st.session_state.get("agreed_terms", False)
        )
        
        if agreement:
            st.session_state["agreed_terms"] = True
            st.success("✅ Anda telah menyetujui ketentuan. Silakan lanjutkan ke menu **'Desain & Preview Undangan'** di atas untuk mulai merancang!")
        else:
            st.session_state["agreed_terms"] = False
            st.warning("⚠️ Harap centang kotak persetujuan di atas untuk membuka akses penuh ke tahap berikutnya.")

    elif "Desain & Preview Undangan" in active_step:
        if not st.session_state.get("agreed_terms", False):
            st.warning("⚠️ Mohon selesaikan dan setujui Syarat & Ketentuan di **Tahap 1** terlebih dahulu.")
        else:
            st.subheader("🎨 2. Data Pernikahan, Tema Visual, Musik & Preview Undangan")
            
            col_form, col_preview = st.columns([1, 1])

            with col_form:
                st.subheader("📋 Informasi Mempelai")
                
                if is_session_active:
                    st.info("🔒 **Mode Terkunci:** Lisensi Anda aktif. Seluruh form isian dan pengaturan desain dikunci untuk menjaga stabilitas undangan yang sudah disebar.")

                groom_name = st.text_input("Nama Mempelai Pria", "Budi", disabled=is_session_active)
                bride_name = st.text_input("Nama Mempelai Wanita", "Siti", disabled=is_session_active)
                
                theme_options = [
                    "✨ Chic & Modern Green", 
                    "⚡ Energetic Sunset Neon", 
                    "🌸 Boho Sunrise Neon", 
                    "🌿 Minimalist Emerald Organic",
                    "🌿 Sage Green Botanical",
                    "☕ Mocha Latte Vintage",
                    "💜 Lavender Dream Royalty",
                    "🌅 Peach Blossom Sunset",
                    "🖤 Dark Luxury Elegance", 
                    "🏛️ Celestial Midnight Starlight",
                    "🌊 Royal Ocean Blue",           
                    "🍷 Burgundy Velvet Romance",     
                    "🌻 Bohemian Sunset Vintage",     
                    "💎 Diamond Silver Crystal",
                    "🌸 Cherry Blossom Japanese Spring",
                    "🌾 Rustic Wheat & Pampas Grass",
                    "❄️ Winter Ice Blue Serenity",
                    "🍋 Mediterranean Lemon & Olive",
                    "🌸 Cherry Blossom Japanese Spring",
                    "🌺 Vibrant Colorful Spring Garden"
                ]
                theme_choice = st.selectbox("Tema Visual AI", theme_options, disabled=is_session_active)

                st.markdown("---")
                st.markdown("#### 💍 Acara Akad Nikah")
                akad_date = st.date_input("Tanggal Akad Nikah", disabled=is_session_active, key="akad_date")
                akad_day = st.text_input("Hari Akad Nikah", "Sabtu", disabled=is_session_active, key="akad_day")
                akad_time = st.text_input("Waktu / Jam Akad Nikah", "08.00 - 10.00 WIB", disabled=is_session_active, key="akad_time")
                akad_location = st.text_input("Lokasi Akad Nikah", "Masjid Agung, Jakarta", disabled=is_session_active, key="akad_loc")
                akad_maps_url = st.text_input("URL Google Maps Akad", "https://maps.google.com", disabled=is_session_active, key="akad_maps")

                st.markdown("---")
                st.markdown("#### 🥳 Acara Resepsi")
                resep_date = st.date_input("Tanggal Resepsi", disabled=is_session_active, key="resep_date")
                resep_day = st.text_input("Hari Resepsi", "Sabtu", disabled=is_session_active, key="resep_day")
                resep_time = st.text_input("Waktu / Jam Resepsi", "11.00 - 13.00 WIB", disabled=is_session_active, key="resep_time")
                resep_location = st.text_input("Lokasi Resepsi", "Gedung Cendrawasih, Jakarta", disabled=is_session_active, key="resep_loc")
                resep_maps_url = st.text_input("URL Google Maps Resepsi", "https://maps.google.com", disabled=is_session_active, key="resep_maps")

                st.markdown("---")
                st.markdown("#### 🤝 Turut Mengundang")
                turut_mengundang = st.text_area(
                    "Turut Mengundang (Gunakan koma atau baris baru)", 
                    "Keluarga Besar Pria:\n- Bp. Ahmad & Ibu Siti\nKeluarga Besar Wanita:\n- Bp. Dahlan & Ibu Aminah", 
                    disabled=is_session_active,
                    height=100
                )
                bank_info = st.text_input("Informasi Amplop Digital / Bank", "BCA 123456789 a.n Budi", disabled=is_session_active)

                st.markdown("---")
                
                st.subheader("🖼️ Galeri Foto")
                uploaded_photos = st.file_uploader(
                    "Upload Foto Galeri (Maksimal 5 foto, @ maks 2MB)",
                    type=["jpg", "jpeg", "png"],
                    accept_multiple_files=True,
                    disabled=is_session_active
                )
                
                gallery_data = []
                
                if uploaded_photos:
                    if len(uploaded_photos) > 5:
                        st.error("⚠️ Maksimal hanya boleh mengupload 5 foto!")
                    else:
                        has_oversized_file = False
                        for photo in uploaded_photos:
                            if photo.size > 2 * 1024 * 1024:
                                st.error(f"⚠️ File {photo.name} terlalu besar! Harap upload foto di bawah 2MB.")
                                has_oversized_file = True
                        
                        if not has_oversized_file:
                            st.markdown("### ✍️ Tulis Keterangan / Cerita Foto:")
                            
                            temp_gallery = []
                            for i, photo in enumerate(uploaded_photos):
                                caption = st.text_input(
                                    f"Cerita untuk Foto {i+1} ({photo.name})",
                                    placeholder="Contoh: Momen saat liburan pertama di luar negeri...",
                                    key=f"caption_{i}"
                                )
                                
                                bytes_data = photo.getvalue()
                                base64_encoded = base64.b64encode(bytes_data).decode("utf-8")
                                img_src = f"data:image/{photo.type.split('/')[-1]};base64,{base64_encoded}"
                                
                                temp_gallery.append({
                                    "photo": img_src,
                                    "caption": caption
                                })
                            
                            st.session_state['gallery_photos'] = temp_gallery
        
                default_photo_url = st.text_input("Atau URL Foto Sampul Utama", "https://images.unsplash.com/photo-1519741497674-611481863552", disabled=is_session_active)

                st.markdown("---")
                st.subheader("🎵 Background Music Player")
                music_option = st.radio("Sumber Musik Background:", ["Preset Musik", "Upload File MP3", "URL MP3 Eksternal"], disabled=is_session_active)
                
                final_music_url = ""
                if music_option == "Preset Musik":
                    preset_choice = st.selectbox("Pilih Lagu Preset:", ["Acoustic Romantic (Instrumental)", "Piano Marriage D'Amour", "Violin Modern Love"], disabled=is_session_active)
                    preset_urls = {
                        "Acoustic Romantic (Instrumental)": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                        "Piano Marriage D'Amour": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
                        "Violin Modern Love": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3"
                    }
                    final_music_url = preset_urls[preset_choice]
                elif music_option == "Upload File MP3":
                    uploaded_audio = st.file_uploader("Upload Musik Latar (MP3/WAV/OGG)", type=["mp3", "wav", "ogg"], disabled=is_session_active)
                    if uploaded_audio:
                        final_music_url = file_to_base64(uploaded_audio)
                        st.success("✅ File musik berhasil dimuat!")
                else:
                    final_music_url = st.text_input("Masukkan Direct URL File MP3", "", disabled=is_session_active)

                st.markdown("---")
                test_guest_name = st.text_input("Nama Tamu Uji Coba (Untuk Preview)", "Budi Sudarsono", disabled=True)
                
                btn_generate = st.button("🚀 Generate & Kunci Desain AI", type="primary", use_container_width=True, disabled=is_session_active)

                if btn_generate:
                    with st.spinner("Agent AI sedang merancang kata-kata & gaya visual..."):
                        prompt = f"Buat 1 kalimat quote cinta indah tema {theme_choice} untuk {groom_name} & {bride_name}. Tentukan kelas Tailwind CSS theme_bg, theme_card_bg, theme_text yang mencerminkan gaya {theme_choice}. Format JSON."

                        gallery_photos = []
                        raw_gallery = st.session_state.get('gallery_photos', [])
                        
                        if raw_gallery and len(raw_gallery) > 0:
                            gallery_photos = raw_gallery
                        else:
                            gallery_photos = [{"photo": default_photo_url, "caption": "Momen Bahagia Kami"}]

                        ai_data, provider_used = generate_ai_content(prompt, theme_choice, groom_name, bride_name)

                        st.info(f"API Provider yang merespons: {provider_used}")

                        st.session_state["design_ready"] = True
                        st.session_state["groom_name"] = groom_name
                        st.session_state["bride_name"] = bride_name

                        try:
                            if os.path.exists("template.html"):
                                with open("template.html", "r", encoding="utf-8") as f:
                                    template_content = f.read()
                            else:
                                st.error("⚠️ File `template.html` tidak ditemukan di direktori project!")
                                template_content = "<h1>Template tidak ditemukan</h1>"

                            jinja_template = Template(template_content)
                            rendered_html = jinja_template.render(
                                groom_name=groom_name,
                                bride_name=bride_name,
                                quote_text=ai_data.get("quote"),
                                akad_date=akad_date.strftime("%d %B %Y"),
                                raw_event_date=akad_date.strftime("%Y-%m-%d"),
                                akad_day=akad_day,
                                akad_time=akad_time,
                                akad_location=akad_location,
                                akad_maps_url=akad_maps_url,
                                resep_date=resep_date.strftime("%d %B %Y"),
                                resep_day=resep_day,
                                resep_time=resep_time,
                                resep_location=resep_location,
                                resep_maps_url=resep_maps_url,
                                turut_mengundang=turut_mengundang,
                                photo_url=gallery_photos[0]["photo"] if gallery_photos else default_photo_url,
                                gallery_photos=gallery_photos,
                                bank_info=bank_info,
                                music_url=final_music_url,
                                guest_name=test_guest_name,
                                theme_bg=ai_data.get("theme_bg", "bg-slate-900"),
                                theme_card_bg=ai_data.get("theme_card_bg", "bg-slate-800"),
                                theme_text=ai_data.get("theme_text", "text-amber-100"),
                                current_user_id=current_user
                            )

                            invitation_payload = {
                                "rendered_html": rendered_html,
                                "groom_name": groom_name,
                                "bride_name": bride_name,
                                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                            save_json(INVITATION_DATA_FILE, invitation_payload)

                            st.session_state["rendered_html"] = rendered_html
                            st.success(f"✅ Undangan Berhasil Dibuat!")
                        except Exception as e:
                            st.error(f"Gagal merender template HTML: {e}")

            with col_preview:
                st.subheader("👁️ Preview Tampilan di HP")
                if "rendered_html" in st.session_state:
                    st.components.v1.html(st.session_state["rendered_html"], height=800, scrolling=True)
                else:
                    st.info("Atur form di sebelah kiri lalu klik 'Generate & Kunci Desain AI' untuk melihat pratinjau.")

    elif "Buat Link Undangan" in active_step:
        base_app_url = "https://wedding-invitation-ai.streamlit.app"

        # KUNCI PERBAIKAN: Selalu ambil user_id yang konsisten dari session_state
        # Baik dari alur normal maupun hasil pemulihan Google Sheets via token URL
        current_user = st.session_state.get("user_id") or st.session_state.get("current_user", "default_user")

        if not st.session_state.get("design_ready", False) and not is_session_active:
            st.warning("⚠️ Silakan selesaikan desain undangan di **Tahap 2** terlebih dahulu.")
        else:
            st.subheader("🚀 3. Redaksi WhatsApp, Link Tamu, & Pembayaran Otomatis")
            
            st.markdown("### 💳 Pembayaran Lisensi Akses 30 Hari (Otomatis via Midtrans)")
            st.info("💡 Sistem pembayaran menggunakan **Midtrans Sandbox (Uji Coba)**.")

            if is_session_active:
                st.success("🎉 **Layanan Aktif!** Lisensi Anda berlaku penuh (Maksimal 30 hari sejak aktivasi). Seluruh fitur tahap 3 dan 4 dapat digunakan.")
                
                active_token = st.session_state.get("user_token", "token-aktif-anda")
                st.markdown("#### 🔗 Link Akses Cadangan (Anti-Putus Sesi)")
                st.info("Simpan tautan berikut untuk membuka kembali Tahap 3 & 4 keesokan harinya jika *browser* tertutup atau laptop *sleep*:")
                st.code(f"{base_app_url}/?token={active_token}", language="markdown")
                
            else:
                st.warning("⚠️ Akses unduh link dan rekap RSVP terkunci. Silakan lakukan pembayaran otomatis di bawah ini.")
                
                with st.form("midtrans_payment_form"):
                    st.markdown("#### Form Data Pembeli")
                    buyer_name = st.text_input("Nama Lengkap", value=st.session_state.get("groom_name", ""))
                    buyer_email = st.text_input("Email Anda", value="client@example.com")
                    buyer_wa = st.text_input("Nomor WhatsApp", value="08123456789")
                    
                    submitted_payment = st.form_submit_button("💳 Bayar Sekarang (Rp 49.000)", type="primary")

                    if submitted_payment:
                        if buyer_name and buyer_email:
                            try:
                                mid_server_key = st.secrets["midtrans"]["server_key"] if "midtrans" in st.secrets else "SB-Mid-server-R1VA5qDJJ5ePzOsP5igqK0Xs"
                                mid_client_key = st.secrets["midtrans"]["client_key"] if "midtrans" in st.secrets else "SB-Mid-client-CDejLrtqwH_UEbTAXSKD23Wv"

                                snap = midtransclient.Snap(
                                    is_production=False,
                                    server_key=mid_server_key,
                                    client_key=mid_client_key
                                )

                                order_id_trx = f"WAI-INV-{int(time.time())}"
                                user_token = str(uuid.uuid4())
                                
                                transaction_params = {
                                    "transaction_details": {
                                        "order_id": order_id_trx,
                                        "gross_amount": 10
                                    },
                                    "customer_details": {
                                        "first_name": buyer_name,
                                        "email": buyer_email,
                                        "phone": buyer_wa
                                    },
                                    "item_details": [{
                                        "id": "LIC-30",
                                        "price": 10,
                                        "quantity": 1,
                                        "name": "Lisensi Wedding AI Invitation 30 Hari"
                                    }]
                                }

                                charge_response = snap.create_transaction(transaction_params)
                                redirect_url = charge_response['redirect_url']
                                
                                save_order_to_gsheets(
                                    order_id=order_id_trx,
                                    token=user_token,
                                    status="PENDING",
                                    user_id=current_user  # Menggunakan current_user yang konsisten
                                )
                                
                                st.success("✅ Link Pembayaran Berhasil Dibuat!")
                                st.markdown(f"👉 **[Klik Di Sini untuk Menyelesaikan Pembayaran]({redirect_url})**", unsafe_allow_html=True)
                                
                            except Exception as e:
                                st.error(f"Gagal terhubung ke Midtrans: {str(e)}")
                        else:
                            st.error("Harap isi Nama dan Email Anda.")

                st.markdown("---")
                st.markdown("#### 🔑 Aktivasi Otomatis / Manual Kode Unik & Token Akses")
                
                code_input = st.text_input("Masukkan Kode Aktivasi / Order ID")
                if st.button("Aktivasi Sekarang"):
                    if code_input.strip():
                        user_token = str(uuid.uuid4())
                        
                        save_order_to_gsheets(
                            order_id=code_input.strip(),
                            token=user_token,
                            status="ACTIVATED",
                            user_id=current_user  # Menggunakan current_user yang konsisten
                        )
                        
                        st.session_state["activated_code_input"] = code_input.strip()
                        st.session_state["user_token"] = user_token
                        st.session_state["is_session_active"] = True  
                        
                        st.success("✅ Aktivasi berhasil! Silakan nikmati akses penuh.")
                        st.info("🔑 **Link Akses Cadangan Anda:** Simpan tautan di bawah ini untuk melanjutkan pekerjaan keesokan harinya:")
                        st.code(f"{base_app_url}/?token={user_token}", language="markdown")
                        
                        if st.button("Masuk ke Fitur Tahap 3 & 4 Sekarang 🚀"):
                            st.rerun()

            # =========================================================
            # FITUR TAMBAHAN: UPLOAD CSV DAFTAR TAMU & GENERATE LINK MASSAL
            # =========================================================
            if is_session_active:
                st.markdown("---")
                st.markdown("### 📋 Upload Daftar Tamu (CSV) & Broadcast WhatsApp")
                st.info("Unggah file CSV berisi daftar nama tamu (kolom harus dinamai **Nama**) untuk men-generate link undangan unik secara massal beserta `user_id` Anda.")

                uploaded_csv = st.file_uploader("Upload File Daftar Tamu (.csv)", type=["csv"])
                
                default_narration = "Tanpa mengurangi rasa hormat, kami mengundang Bapak/Ibu/Saudara/i untuk menghadiri acara pernikahan kami. Berikut link undangan digital:\n{link_undangan}\n\nMerupakan suatu kehormatan dan kebahagiaan bagi kami apabila Bapak/Ibu/Saudara/i berkenan hadir."
                
                custom_narration = st.text_area("Modifikasi Narasi / Pesan WhatsApp:", value=default_narration, height=120)
                st.caption("Gunakan `{link_undangan}` di dalam teks untuk menempatkan tautan undangan secara otomatis.")

                if uploaded_csv is not None:
                    try:
                        df_guests = pd.read_csv(uploaded_csv)
                        if 'Nama' not in df_guests.columns:
                            st.error("⚠️ File CSV harus memiliki kolom dengan header bernama **Nama**.")
                        else:
                            st.success(f"✅ Berhasil memuat {len(df_guests)} data tamu dari file CSV.")
                            
                            base_app_url = "https://wedding-invitation-ai.streamlit.app/"
                            
                            generated_links = []
                            for idx, row in df_guests.iterrows():
                                guest_n = str(row['Nama'])
                                link_item = f"{base_app_url}?to={urllib.parse.quote(guest_n)}&user_id={current_user}"
                                message_text = custom_narration.replace("{link_undangan}", link_item)
                                
                                generated_links.append({
                                    "Nama Tamu": guest_n,
                                    "Link Undangan": link_item,
                                    "Format Pesan WhatsApp": message_text
                                })
                            
                            df_result = pd.DataFrame(generated_links)
                            st.markdown("#### 📊 Hasil Generate Link Undangan Unik:")
                            st.dataframe(df_result, use_container_width=True, hide_index=True)

                            csv_output = df_result.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label="📥 Download Daftar Link Undangan (CSV)",
                                data=csv_output,
                                file_name=f"link_undangan_tamu_{current_user}.csv",
                                mime="text/csv"
                            )
                    except Exception as e:
                        st.error(f"Gagal memproses file CSV: {e}")
                else:
                    st.markdown("#### ✍️ Atau Generate Link untuk 1 Tamu:")
                    single_guest = st.text_input("Nama Tamu Satuan", "Bapak Budi & Keluarga")
                    if single_guest:
                        single_link = f"https://wedding-invitation-ai.streamlit.app/?to={urllib.parse.quote(single_guest)}&user_id={current_user}"
                        st.markdown("Link Undangan Satuan:")
                        st.code(single_link, language="markdown")

    elif "Manajemen RSVP Tamu" in active_step:
        st.subheader("📊 4. Manajemen RSVP & Buku Tamu Digital")
        
        if not is_session_active:
            st.error("🔒 **Menu Terkunci!** Manajemen RSVP dan pemantauan tamu digital hanya aktif jika Anda telah memasukkan kode aktivasi layanan pada **Tahap 3**.")
        else:
            GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSsaN2n7MKVozzpZ-61okbgxjp8JE1CgA6HG2TUEn2AMqBDFOJ3vdtHeTlJDngnlIFa7P3zgf1ppzvX/pub?gid=0&single=true&output=csv"
            
            if "MASUKKAN_URL" in GOOGLE_SHEET_CSV_URL:
                st.warning("⚠️ URL CSV Google Sheet belum dikonfigurasi di Tahap 4 app.py.")
            else:
                try:
                    df_all = pd.read_csv(GOOGLE_SHEET_CSV_URL)
                    df_all.columns = df_all.columns.str.strip()
                    
                    df_rsvp = df_all[df_all['User_ID'].astype(str).str.lower() == str(current_user).lower()]
                    
                    if df_rsvp.empty:
                        st.info(f"Belum ada data RSVP masuk untuk ID Pengguna: `{current_user}`")
                    else:
                        total_respon = len(df_rsvp)
                        total_hadir = len(df_rsvp[df_rsvp['Kehadiran'] == 'Hadir']) if 'Kehadiran' in df_rsvp.columns else 0
                        total_ragu = len(df_rsvp[df_rsvp['Kehadiran'] == 'Ragu-ragu']) if 'Kehadiran' in df_rsvp.columns else 0
                        total_absen = len(df_rsvp[df_rsvp['Kehadiran'] == 'Maaf, Tidak Bisa Hadir']) if 'Kehadiran' in df_rsvp.columns else 0

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Total Respon Tamu", total_respon)
                        m2.metric("Pasti Hadir", total_hadir)
                        m3.metric("Ragu-Ragu", total_ragu)
                        m4.metric("Tidak Hadir", total_absen)

                        st.markdown("---")
                        st.markdown("**📋 Rekap Tabel Kehadiran & Ucapan Doa:**")
                        st.dataframe(df_rsvp, use_container_width=True, hide_index=True)

                        csv_rsvp = df_rsvp.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Download Hasil Rekap RSVP (CSV)", data=csv_rsvp, file_name=f"rekap_rsvp_{current_user}.csv", mime="text/csv")

                except Exception as e:
                    st.error(f"Gagal memuat data dari Google Sheet: {e}")
