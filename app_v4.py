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

# =========================================================
# 0. ROUTER TAMU UNDANGAN (DIBUKA DARI LINK TAMU)
# =========================================================
query_params = st.query_params
target_guest = query_params.get("to") or query_params.get("guest")
target_user_id = query_params.get("user_id")
target_tpl = query_params.get("tpl", "template01")  # Menangkap parameter tpl (default: template01)

# Jika parameter 'to' atau 'guest' ditemukan, jalankan mode tampilan Tamu Undangan
if target_guest:
    st.set_page_config(page_title=f"Undangan Pernikahan — {target_guest}", layout="centered")
    
    # Memuat data undangan tersimpan dari file JSON
    invitation_db = load_json(INVITATION_DATA_FILE, {})
    
    # Ambil kamus rendered_templates dari file JSON
    rendered_templates = invitation_db.get("rendered_templates", {})
    
    # Cek apakah template yang diminta tersedia
    if target_tpl in rendered_templates:
        html_content = rendered_templates[target_tpl]
        
        # Ganti placeholder nama tamu di HTML dengan nama tamu asli dari URL
        # Lakukan penggantian untuk beberapa kemungkinan penulisan placeholder
        html_content = html_content.replace("Nadia & Keluarga", target_guest)
        html_content = html_content.replace("Budi Sudarsono", target_guest)
        
        # Render tampilan undangan digital untuk tamu
        st.components.v1.html(html_content, height=900, scrolling=True)
    else:
        st.warning(f"⚠️ Undangan dengan template `{target_tpl}` belum di-generate oleh pemilik acara.")
    
    # Hentikan eksekusi agar dashboard admin/klien di bawah tidak dirender untuk tamu
    st.stop()

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
# KONDISI 2: KLIEN (WEDDING GENERATOR MULTI-TEMPLATE)
# =========================================================
else:
    # URL Background Dashboard
    bg_image_url = "https://images.unsplash.com/photo-1519741497674-611481863552?w=1600&h=1000&fit=crop"

    if "agreed_terms" not in st.session_state:
        st.session_state["agreed_terms"] = False

    # Inisialisasi state untuk pilihan multi-template (List)
    if "selected_templates" not in st.session_state:
        st.session_state["selected_templates"] = ["template01"]

    # Inisialisasi state untuk alur navigasi aktif jika belum ada
    if "active_step_idx" not in st.session_state:
        st.session_state["active_step_idx"] = 0

    is_session_active = st.session_state.get("is_session_active", False)

    # Styling CSS Kustom untuk Background & Kartu Alur Navigasi
    st.markdown(f"""
        <style>
        .stApp {{
            background-image: linear-gradient(rgba(0, 0, 0, 0.35), rgba(0, 0, 0, 0.35)), url("{bg_image_url}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}
        div.block-container {{
            background-color: rgba(248, 245, 238, 0.92);
            padding: 2.5rem 2rem;
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
            margin-top: 1.5rem;
            margin-bottom: 2rem;
        }}
        .step-nav-card {{
            background: #ffffff;
            border: 2px solid #B8860B;
            border-radius: 16px;
            padding: 15px 10px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(225, 29, 72, 0.08);
            margin-bottom: 10px;
        }}
        .step-circle {{
            background: #B8860B;
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
        }}
        .step-title {{
            color: #B8860B;
            font-weight: bold;
            font-size: 13px;
            margin-bottom: 4px;
        }}
        .step-desc {{
            color: #B8860B;
            font-size: 10px;
            line-height: 1.3;
        }}
        </style>
    """, unsafe_allow_html=True)

    st.markdown("<p style='color: #B8860B; font-weight: bold;'>🧭 Alur Pembuatan Undangan Digital Multi-Template:</p>", unsafe_allow_html=True)

    # Daftar tahapan alur beserta deskripsinya
    steps_info = [
        {"num": "1", "title": "Panduan & Pilih Multi-Template", "desc": "Baca ketentuan, pilih 1-5 template (01-20), & setujui syarat."},
        {"num": "2", "title": "Desain & Preview Switcher", "desc": "Isi data mempelai & ganti-ganti preview untuk setiap template yang dipilih."},
        {"num": "3", "title": "Buat Link Undangan Multi-CSV", "desc": "Aktivasi Layanan, upload CSV per template, Download Link Undangan."},
        {"num": "4", "title": "Manajemen RSVP Terpadu", "desc": "Pantau kehadiran & ucapan dari semua segmen tamu dalam 1 dashboard."}
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
            st.markdown(f"""
                <div class="step-nav-card" style="border-color: #B8860B;">
                    <div class="step-circle">{info['num']}</div>
                    <div class="step-title">{info['title']}</div>
                    <div class="step-desc">{info['desc']}</div>
                </div>
            """, unsafe_allow_html=True)
            
            btn_label = f"Tahap {info['num']}"
            is_active = (st.session_state["active_step_idx"] == real_idx)
            btn_type = "primary" if is_active else "secondary"
            
            if st.button(btn_label, key=f"nav_btn_{real_idx}", type=btn_type, use_container_width=True):
                st.session_state["active_step_idx"] = real_idx
                st.rerun()

    full_menu_list = [
        "1️⃣ Panduan & Pilih Multi-Template ➡️",
        "2️⃣ Desain & Preview Switcher ➡️",
        "3️⃣ Buat Link Undangan Multi-CSV ➡️",
        "4️⃣ Manajemen RSVP Terpadu"
    ]
    if is_session_active:
        menu_steps_mapping = full_menu_list[2:]
    else:
        menu_steps_mapping = full_menu_list

    # Penanganan index aman
    current_idx = st.session_state["active_step_idx"] if not is_session_active else (st.session_state["active_step_idx"] - 2)
    current_idx = max(0, min(current_idx, len(menu_steps_mapping) - 1))
    active_step = menu_steps_mapping[current_idx]

    # =========================================================
    # TAHAP 1: LANDING WOW - FIX ANTI KEDIP + 5 PILIH MULUS
    # =========================================================
    if "Panduan & Pilih Multi-Template" in active_step or "Panduan Aplikasi" in active_step:
        import os
        import streamlit.components.v1 as components

        def get_thumb_url(tpl_name, w=400, h=600):
            num = int(tpl_name.replace("template",""))
            thumbs = [
                "https://images.unsplash.com/photo-1519741497674-611481863552?w=400&h=600&fit=crop",
                "https://images.unsplash.com/photo-1522673607200-164d1b6ce486?w=400&h=600&fit=crop",
                "https://images.unsplash.com/photo-1511285560929-80b456fea0bc?w=400&h=600&fit=crop",
                "https://images.unsplash.com/photo-1465495976277-4387d4b0b4c6?w=400&h=600&fit=crop",
            ]
            base = thumbs[num % len(thumbs)]
            return base.replace("w=400&h=600", f"w={w}&h={h}") + f"&tpl={tpl_name}"

        if "selected_templates" not in st.session_state:
            st.session_state["selected_templates"] = ["template01"]
        if "preview_tpl" not in st.session_state:
            st.session_state["preview_tpl"] = None

        @st.dialog("👁 Preview Template", width="large")
        def preview_dialog(tpl_name):
            file_path = f"{tpl_name}.html"
            static_path = f"static/{tpl_name}.html"
            st.markdown(f"<div style='text-align:center'><h3 style='margin:0'>{tpl_name.upper()}.HTML</h3></div>", unsafe_allow_html=True)
            found_path = None
            if os.path.exists(file_path): found_path = file_path
            elif os.path.exists(static_path): found_path = static_path
            if found_path:
                st.success(f"✅ File asli: {found_path}")
                with open(found_path, 'r', encoding='utf-8', errors='ignore') as f:
                    html_content = f.read()
                components.html(html_content, height=700, scrolling=True)
            else:
                st.warning(f"⚠️ {file_path} belum ada — fallback dummy")
                st.image(get_thumb_url(tpl_name, w=800, h=1200), use_container_width=True)
            if st.button("❌ Tutup", use_container_width=True):
                st.session_state["preview_tpl"] = None
                st.rerun()
            if st.button("✅ Pilih Template Ini", type="primary", use_container_width=True):
                if tpl_name not in st.session_state["selected_templates"] and len(st.session_state["selected_templates"]) < 5:
                    st.session_state["selected_templates"].append(tpl_name)
                st.session_state["preview_tpl"] = None
                st.rerun()

        # kalau ada preview yang dipencet dari fragment
        if st.session_state["preview_tpl"]:
            preview_dialog(st.session_state["preview_tpl"])

        st.markdown("""
        <style>
        .stApp{background:#FFFBF2!important}
        div.block-container{background:#fff!important;padding:0!important;max-width:1150px!important}
        .wow-hero{text-align:center;padding:28px 20px 14px 20px;border-bottom:1px solid #F3E9D9}
        .wow-badge{background:#111;color:#FFE45E;padding:6px 14px;border-radius:99px;font-size:11px;font-weight:800}
        .wow-title{font-size:clamp(32px,8vw,52px);font-weight:900;line-height:.9;letter-spacing:-2px;color:#111;margin-top:16px}
        .wow-title span{background:#FFE45E;padding:0 10px;transform:rotate(-1.5deg);display:inline-block}
        .wow-sub{font-size:13px;color:#6B4E31;max-width:520px;margin:12px auto 0 auto}
        .cat-title{font-weight:900;font-size:14px;color:#111;margin:26px 0 10px 18px}
        /* BIKIN COLUMNS JADI SCROLL, BUKAN WRAP */
        div[data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;overflow-x:auto!important;gap:14px!important;padding:0 18px 16px 18px!important}
        div[data-testid="stHorizontalBlock"]::-webkit-scrollbar{height:6px}
        div[data-testid="stHorizontalBlock"]::-webkit-scrollbar-thumb{background:#E8D5B5;border-radius:99px}

        st.markdown("""
        <style>
        .stApp{background:#FFFBF2!important}
        div.block-container{background:#fff!important;padding:0!important;max-width:1150px!important}
        .wow-hero{text-align:center;padding:28px 20px 14px 20px;border-bottom:1px solid #F3E9D9}
        .wow-badge{background:#111;color:#FFE45E;padding:6px 14px;border-radius:99px;font-size:11px;font-weight:800}
        .wow-title{font-size:clamp(32px,8vw,52px);font-weight:900;line-height:.9;letter-spacing:-2px;color:#111;margin-top:16px}
        .wow-title span{background:#FFE45E;padding:0 10px;transform:rotate(-1.5deg);display:inline-block}
        .wow-sub{font-size:13px;color:#6B4E31;max-width:520px;margin:12px auto 0 auto}
        .cat-title{font-weight:900;font-size:14px;color:#111;margin:26px 0 10px 18px}
        div[data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;overflow-x:auto!important;overflow-y:hidden!important;gap:14px!important;padding:0 18px 16px 18px!important;scroll-snap-type:x mandatory!important}
        div[data-testid="stHorizontalBlock"]::-webkit-scrollbar{height:6px}
        div[data-testid="stHorizontalBlock"]::-webkit-scrollbar-thumb{background:#E8D5B5;border-radius:99px}
        div[data-testid="column"]{min-width:19%!important;max-width:19%!important;flex:0 0 19%!important;scroll-snap-align:start!important}
        .h-card{background:#fff;border:2px solid #F3E9D9;border-radius:16px;overflow:hidden}
        .h-card.selected{border-color:#111!important;border-width:2.5px;box-shadow:4px 4px 0 #FFE45E}
        .h-card img{width:100%;height:185px;object-fit:cover;display:block}
        @media(max-width:768px){div[data-testid="column"]{min-width:46%!important;max-width:46%!important;flex:0 0 46%!important}}
        div[data-testid="stStatusWidget"]{display:none!important}
        </style>
        """, unsafe_allow_html=True)
        
        .h-card{background:#fff;border:2px solid #F3E9D9;border-radius:16px;overflow:hidden}
        .h-card.selected{border-color:#111!important;border-width:2.5px;box-shadow:4px 4px 0 #FFE45E}
        .h-card img{width:100%;height:185px;object-fit:cover;display:block}
        @media(max-width:768px){div[data-testid="column"]{min-width:46%!important;max-width:46%!important;flex:0 0 46%!important}}
        /* HILANGKAN POPUP RUNNING YANG GANGGU */
        div[data-testid="stStatusWidget"]{display:none!important}
        </style>
        """, unsafe_allow_html=True)

        st.markdown('<div class="wow-hero"><div class="wow-badge">✨ ANTI KEDIP • NO RELOAD POPUP</div><div class="wow-title">PILIH TEMPLATE<br>SESUAI<br><span>SEGMEN TAMU</span></div><div class="wow-sub">Klik +Pilih sekarang mulus, tanpa window kedip. Geser ke kanan →</div></div>', unsafe_allow_html=True)

        categories = {
            "💼 Temen Kantor - Formal & Elegan": ["template01","template02","template03","template04","template05","template06","template07","template08"],
            "🏡 Ortu & Tetangga - Tradisional & Local Wisdom": ["template09","template10","template11","template12","template13","template14","template05","template06"],
            "🎓 Nongkrong & Kuliah - Gaul & Ceria": ["template15","template16","template17","template18","template19","template20","template02","template07"],
            "🎮 Temen Mabar - Fun & Gaming Vibes": ["template01","template08","template15","template16","template03","template04","template17","template18"],
            "🕌 Temen Alim - Religius & Berkah": ["template09","template10","template11","template19","template20","template12","template13","template14"],
        }

        @st.fragment
        def render_categories():
            for cat_name, tpl_list in categories.items():
                st.markdown(f"<div class='cat-title'>{cat_name} <span style='font-size:11px;color:#8B7355;font-weight:600'>— geser →</span></div>", unsafe_allow_html=True)
                cols = st.columns(len(tpl_list))
                for idx, tpl in enumerate(tpl_list):
                    is_sel = tpl in st.session_state["selected_templates"]
                    badge = "📄" if os.path.exists(f"{tpl}.html") or os.path.exists(f"static/{tpl}.html") else "🖼️"
                    with cols[idx]:
                        border = "2.5px solid #111;box-shadow:4px 4px 0 #FFE45E" if is_sel else "2px solid #F3E9D9"
                        st.markdown(f"<div class='h-card' style='border:{border}'><img src='{get_thumb_url(tpl)}'><div style='padding:8px 10px;display:flex;justify-content:space-between'><b style='font-size:11px'>{badge} {tpl.upper()}</b><span>{'✓' if is_sel else '+'}</span></div></div>", unsafe_allow_html=True)
                        if st.button("👁 Preview", key=f"prev_{cat_name}_{tpl}_{idx}", use_container_width=True):
                            st.session_state["preview_tpl"] = tpl
                            st.rerun()
                        if is_sel:
                            if st.button("✓ Hapus", key=f"del_{cat_name}_{tpl}_{idx}", use_container_width=True):
                                if len(st.session_state["selected_templates"]) > 1:
                                    st.session_state["selected_templates"].remove(tpl)
                                st.rerun()
                        else:
                            if st.button("+ Pilih", key=f"pick_{cat_name}_{tpl}_{idx}", use_container_width=True):
                                if len(st.session_state["selected_templates"]) < 5:
                                    st.session_state["selected_templates"].append(tpl)
                                    st.session_state["selected_templates"] = list(dict.fromkeys(st.session_state["selected_templates"]))
                                else:
                                    st.toast("Maksimal 5 bro!", icon="🚫")
                                st.rerun()

        render_categories()

        selected_tpls = st.session_state["selected_templates"]
        st.markdown(f'<div style="position:sticky;bottom:0;background:#111;color:white;padding:14px 18px;display:flex;justify-content:space-between;align-items:center;margin-top:18px;border-radius:18px 18px 0 0;z-index:20;"><div><b style="font-size:13px;">{len(selected_tpls)} template dipilih</b><br><span style="font-size:11px;opacity:.6;">{", ".join(selected_tpls)}</span></div><div style="background:#FFE45E;color:black;padding:6px 12px;border-radius:99px;font-size:12px;font-weight:900;">SIAP LANJUT →</div></div>', unsafe_allow_html=True)
        st.info(f"✨ Terpilih: **{', '.join(selected_tpls)}**")
        agreement = st.checkbox("Saya setuju syarat & privacy", value=st.session_state.get("agreed_terms", False))
        st.session_state["agreed_terms"] = agreement
        if agreement:
            if st.button("🚀 Lanjutkan Isi Data →", type="primary", use_container_width=True):
                st.session_state["active_step_idx"] = 1
                st.rerun()

    # =========================================================
    # TAHAP 2: DESAIN & PREVIEW SWITCHER UNDANGAN MULTI-TEMPLATE
    # =========================================================
    elif "Desain & Preview" in active_step or "Preview Switcher" in active_step:
        if not st.session_state.get("agreed_terms", False):
            st.warning("⚠️ Mohon pilih template dan setujui Syarat & Ketentuan di **Tahap 1** terlebih dahulu.")
        else:
            selected_templates_list = st.session_state.get("selected_templates", ["template01"])
            st.subheader(f"🎨 2. Data Pernikahan & Preview Switcher ({len(selected_templates_list)} Template Terpilih)")
            
            col_form, col_preview = st.columns([1, 1])

            with col_form:
                st.subheader("📋 Form Isian Utama (Berlaku untuk Semua Template)")
                
                if is_session_active:
                    st.info("🔒 **Mode Terkunci:** Lisensi Anda aktif. Seluruh form isian dan pengaturan desain dikunci untuk menjaga stabilitas undangan yang sudah disebar.")

                # HALAMAN 1: COVER UTAMA & IDENTITAS MEMPELAI
                with st.expander("📌 Halaman 1: Cover & Identitas Utama", expanded=True):
                    cover_photo = st.file_uploader("Foto Cover Halaman Pertama", type=["jpg", "jpeg", "png"], key="cover_img", disabled=is_session_active)
                    cover_photo_url = file_to_base64(cover_photo) if cover_photo else st.text_input("Atau URL Foto Cover", "https://images.unsplash.com/photo-1519741497674-611481863552", disabled=is_session_active)
                    
                    couple_initials = st.text_input("Singkatan Nama Kedua Mempelai", "A & A", disabled=is_session_active, help="Contoh: A & A atau A & H")
                    groom_name = st.text_input("Nama Lengkap Mempelai Pria", "Aditya Pratama, S.T", disabled=is_session_active)
                    groom_name_short = st.text_input("Nama Pendek Mempelai Pria", "Aditya", disabled=is_session_active)
                    bride_name = st.text_input("Nama Lengkap Mempelai Wanita", "Aruna Kirana Putri, S.Arch", disabled=is_session_active)
                    bride_name_short = st.text_input("Nama Pendek Mempelai Wanita", "Aruna", disabled=is_session_active)

                # HALAMAN 2: DETAIL FOTO, ORANG TUA & NARASI PENGANTAR
                with st.expander("📌 Halaman 2: Foto Personal, Orang Tua & Narasi", expanded=False):
                    intro_greeting = st.text_area(
                        "Narasi Pengantar Halaman 2", 
                        "Dengan memohon rahmat dan ridho Allah SWT, kami bermaksud menyelenggarakan pernikahan putra-putri kami:",
                        disabled=is_session_active
                    )

                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        b_photo = st.file_uploader("Foto Mempelai Wanita (Sendiri)", type=["jpg", "jpeg", "png"], key="b_photo_file", disabled=is_session_active)
                        bride_photo = file_to_base64(b_photo) if b_photo else st.text_input("URL Foto Wanita", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&h=500&fit=crop", disabled=is_session_active)
                    with col_p2:
                        g_photo = st.file_uploader("Foto Mempelai Pria (Sendiri)", type=["jpg", "jpeg", "png"], key="g_photo_file", disabled=is_session_active)
                        groom_photo = file_to_base64(g_photo) if g_photo else st.text_input("URL Foto Pria", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=500&fit=crop", disabled=is_session_active)

                    bride_parents = st.text_input("Nama Orang Tua Mempelai Wanita", "Bapak H. Darmawan Putri & Ibu Hj. Siti Aminah", disabled=is_session_active)
                    groom_parents = st.text_input("Nama Orang Tua Mempelai Pria", "Bapak H. Hendra Pratama & Ibu Hj. Rina Marlina", disabled=is_session_active)

                # HALAMAN 3: AKAD, RESEPSI & COUNTDOWN
                with st.expander("📌 Halaman 3: Jadwal Acara & Lokasi", expanded=False):
                    st.markdown("#### 💍 Akad Nikah")
                    akad_date = st.date_input("Tanggal Akad Nikah", disabled=is_session_active, key="akad_date")
                    akad_time = st.text_input("Waktu / Jam Akad", "08.00 WIB s/d Selesai", disabled=is_session_active, key="akad_time")
                    akad_venue = st.text_input("Nama Tempat Akad", "Masjid Agung Trans Studio", disabled=is_session_active, key="akad_venue")
                    akad_address = st.text_area("Alamat Lengkap Akad", "Jl. Gatot Subroto No.289, Bandung", disabled=is_session_active, key="akad_addr")
                    akad_maps_url = st.text_input("URL Google Maps Akad", "https://maps.google.com", disabled=is_session_active, key="akad_maps")

                    st.markdown("---")
                    st.markdown("#### 🥳 Resepsi Pernikahan")
                    resep_date = st.date_input("Tanggal Resepsi", disabled=is_session_active, key="resep_date")
                    resep_time = st.text_input("Waktu / Jam Resepsi", "11.00 - 14.00 WIB", disabled=is_session_active, key="resep_time")
                    resep_venue = st.text_input("Nama Tempat Resepsi", "The Trans Luxury Hotel Ballroom", disabled=is_session_active, key="resep_venue")
                    resep_address = st.text_area("Alamat Lengkap Resepsi", "Jl. Gatot Subroto No.289, Bandung", disabled=is_session_active, key="resep_addr")
                    resep_maps_url = st.text_input("URL Google Maps Resepsi", "https://maps.google.com", disabled=is_session_active, key="resep_maps")

                # HALAMAN 4: OUR STORY
                with st.expander("📌 Halaman 4: Our Story (Perjalanan Cinta)", expanded=False):
                    story_img = st.file_uploader("Foto Ilustrasi Our Story", type=["jpg", "jpeg", "png"], key="story_img_file", disabled=is_session_active)
                    story_photo = file_to_base64(story_img) if story_img else st.text_input("URL Foto Story", "https://images.unsplash.com/photo-1511285560929-80b456fea0bc?w=600&h=400&fit=crop", disabled=is_session_active)
                    
                    st.markdown("#### Babak 1")
                    story_date_1 = st.text_input("Tanggal/Bulan Babak 1", "Januari 2021", disabled=is_session_active)
                    story_title_1 = st.text_input("Judul Babak 1", "Pertama Bertemu", disabled=is_session_active)
                    story_desc_1 = st.text_area("Narasi Babak 1", "Takdir mempertemukan kami di sebuah galeri seni rupa di kawasan Braga, Bandung, berdiskusi tentang arsitektur dan impian masa depan.", disabled=is_session_active)

                    st.markdown("#### Babak 2")
                    story_date_2 = st.text_input("Tanggal/Bulan Babak 2", "Maret 2024", disabled=is_session_active)
                    story_title_2 = st.text_input("Judul Babak 2", "Komitmen Bersama", disabled=is_session_active)
                    story_desc_2 = st.text_area("Narasi Babak 2", "Setelah melalui berbagai suka dan duka bersama dalam karier dan pendidikan, kami memutuskan untuk membawa hubungan ini ke jenjang serius.", disabled=is_session_active)

                    st.markdown("#### Babak 3")
                    story_date_3 = st.text_input("Tanggal/Bulan Babak 3", "Oktober 2026", disabled=is_session_active)
                    story_title_3 = st.text_input("Judul Babak 3", "Menuju Halal", disabled=is_session_active)
                    story_desc_3 = st.text_area("Narasi Babak 3", "Hari yang paling dinantikan akhirnya tiba. Kami siap mengikat janji suci sehidup semati dalam ikatan pernikahan yang diridhoi-Nya.", disabled=is_session_active)

                # HALAMAN 5: GALERI FOTO
                with st.expander("📌 Halaman 5: Galeri Foto Prewedding", expanded=False):
                    uploaded_gallery = st.file_uploader(
                        "Upload Galeri (Maksimal 5 Foto)",
                        type=["jpg", "jpeg", "png"],
                        accept_multiple_files=True,
                        disabled=is_session_active,
                        key="gallery_uploader"
                    )
                    
                    gallery_list = []
                    if uploaded_gallery:
                        for f in uploaded_gallery[:5]:
                            gallery_list.append(file_to_base64(f))
                    else:
                        gallery_list = [
                            "https://images.unsplash.com/photo-1519741497674-611481863552?w=800&h=600&fit=crop",
                            "https://images.unsplash.com/photo-1465495976277-4387d4b0b4c6?w=400&h=500&fit=crop",
                            "https://images.unsplash.com/photo-1522673607200-164d1b6ce486?w=400&h=500&fit=crop"
                        ]

                # HALAMAN 6 & 7
                with st.expander("📌 Halaman 6: RSVP & Buku Tamu", expanded=False):
                    st.info("Formulir RSVP dan daftar ucapan tamu otomatis aktif dan terhubung ke backend Google Sheets.")

                with st.expander("📌 Halaman 7: Penutup & Ayat Pernikahan", expanded=False):
                    c_photo = st.file_uploader("Foto Background Penutup", type=["jpg", "jpeg", "png"], key="closing_img_file", disabled=is_session_active)
                    closing_photo = file_to_base64(c_photo) if c_photo else st.text_input("Atau URL Foto Background Penutup", "https://images.unsplash.com/photo-1519741497674-611481863552", disabled=is_session_active)
                    
                    quote_text = st.text_area(
                        "Kutipan Pernikahan",
                        "“Dan di antara tanda-tanda (kebesaran)-Nya ialah Dia menciptakan pasangan-pasangan untukmu dari jenismu sendiri, agar kamu cenderung dan merasa tenteram kepadanya, dan Dia menjadikan di antaramu rasa kasih dan sayang (QS Ar-Rum : 31).”",
                        disabled=is_session_active
                    )

                # MUSIK LATAR
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
                
                # TOMBOL GENERATE UNTUK SEMUA TEMPLATE TERPILIH
                btn_generate = st.button(f"🚀 Generate & Render ({len(selected_templates_list)} Template)", type="primary", use_container_width=True, disabled=is_session_active)

                if btn_generate:
                    with st.spinner(f"Merangkai data untuk {len(selected_templates_list)} template terpilih..."):
                        rendered_templates = {}
                        
                        for tpl_name in selected_templates_list:
                            target_tpl_file = f"{tpl_name}.html"
                            template_filename = target_tpl_file if os.path.exists(target_tpl_file) else "template.html"

                            if os.path.exists(template_filename):
                                with open(template_filename, "r", encoding="utf-8") as f:
                                    template_content = f.read()
                            else:
                                template_content = f"<h1>Template {tpl_name} tidak ditemukan. Memakai fallback template.</h1>"

                            jinja_template = Template(template_content)
                            rendered_html = jinja_template.render(
                                couple_initials=couple_initials,
                                groom_name=groom_name,
                                groom_name_short=groom_name_short,
                                bride_name=bride_name,
                                bride_name_short=bride_name_short,
                                bride_photo=bride_photo,
                                groom_photo=groom_photo,
                                bride_parents=bride_parents,
                                groom_parents=groom_parents,
                                intro_greeting=intro_greeting,
                                akad_date=akad_date.strftime("%d %B %Y"),
                                raw_event_date=akad_date.strftime("%Y-%m-%d"),
                                akad_time=akad_time,
                                akad_venue=akad_venue,
                                akad_address=akad_address,
                                akad_maps_url=akad_maps_url,
                                resep_date=resep_date.strftime("%d %B %Y"),
                                resep_time=resep_time,
                                resep_venue=resep_venue,
                                resep_address=resep_address,
                                resep_maps_url=resep_maps_url,
                                event_city=resep_address.split(",")[-1].strip() if resep_address else "Bandung",
                                story_photo=story_photo,
                                story_date_1=story_date_1,
                                story_title_1=story_title_1,
                                story_desc_1=story_desc_1,
                                story_date_2=story_date_2,
                                story_title_2=story_title_2,
                                story_desc_2=story_desc_2,
                                story_date_3=story_date_3,
                                story_title_3=story_title_3,
                                story_desc_3=story_desc_3,
                                gallery_list=gallery_list,
                                quote_text=quote_text,
                                closing_photo=closing_photo,
                                photo_url=cover_photo_url,
                                music_url=final_music_url,
                                guest_name=test_guest_name,
                                current_user_id=current_user
                            )
                            rendered_templates[tpl_name] = rendered_html

                        st.session_state["rendered_templates"] = rendered_templates
                        st.session_state["design_ready"] = True
                        st.session_state["groom_name"] = groom_name
                        st.session_state["bride_name"] = bride_name

                        # PENYESUAIAN STRUKTUR PENYIMPANAN MULTI-TEMPLATE & USER_ID
                        invitation_payload = {
                            "user_id": current_user,  # Menyertakan ID Pengguna agar sinkron saat link tamu dibuka
                            "rendered_templates": rendered_templates,
                            "groom_name": groom_name,
                            "bride_name": bride_name,
                            "templates_used": selected_templates_list,
                            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        
                        save_json(INVITATION_DATA_FILE, invitation_payload)
                        st.success(f"✅ Berhasil merender dan menyimpan {len(selected_templates_list)} template undangan!")

            # KOLOM KANAN: PREVIEW SWITCHER
            with col_preview:
                st.subheader("👁️ Preview Switcher Tampilan HP")
                
                rendered_templates = st.session_state.get("rendered_templates", {})
                
                if rendered_templates:
                    preview_choice = st.selectbox(
                        "🔍 Pilih Template yang Ingin Dipreview:",
                        options=list(rendered_templates.keys()),
                        help="Tampilan preview di bawah akan berubah sesuai dengan template yang Anda pilih."
                    )
                    
                    st.info(f"📱 Menampilkan Pratinjau: **{preview_choice}**")
                    st.components.v1.html(rendered_templates[preview_choice], height=800, scrolling=True)
                else:
                    st.info("Silakan atur data di sebelah kiri lalu klik tombol **Generate & Render** untuk melihat pratinjau.")

    # =========================================================
    # TAHAP 2: DESAIN & PREVIEW UNDANGAN
    # =========================================================
    elif "Desain & Preview Undangan" in active_step:
        if not st.session_state.get("agreed_terms", False):
            st.warning("⚠️ Mohon selesaikan dan setujui Syarat & Ketentuan di **Tahap 1** terlebih dahulu.")
        else:
            st.subheader("🎨 2. Data Pernikahan, Tema Visual, Musik & Preview Undangan")
            
            col_form, col_preview = st.columns([1, 1])

            with col_form:
                st.subheader("📋 Form Isian Premium (7 Halaman)")
                
                if is_session_active:
                    st.info("🔒 **Mode Terkunci:** Lisensi Anda aktif. Seluruh form isian dan pengaturan desain dikunci untuk menjaga stabilitas undangan yang sudah disebar.")

                # =========================================================
                # HALAMAN 1: COVER UTAMA & IDENTITAS MEMPELAI
                # =========================================================
                with st.expander("📌 Halaman 1: Cover & Identitas Utama", expanded=True):
                    cover_photo = st.file_uploader("Foto Cover Halaman Pertama", type=["jpg", "jpeg", "png"], key="cover_img", disabled=is_session_active)
                    cover_photo_url = file_to_base64(cover_photo) if cover_photo else st.text_input("Atau URL Foto Cover", "https://images.unsplash.com/photo-1519741497674-611481863552", disabled=is_session_active)
                    
                    couple_initials = st.text_input("Singkatan Nama Kedua Mempelai", "A & A", disabled=is_session_active, help="Contoh: A & A atau A & H")
                    groom_name = st.text_input("Nama Lengkap Mempelai Pria", "Aditya Pratama, S.T", disabled=is_session_active)
                    bride_name = st.text_input("Nama Lengkap Mempelai Wanita", "Aruna Kirana Putri, S.Arch", disabled=is_session_active)



    elif "Buat Link Undangan" in active_step:
        base_app_url = "https://wedding-invitation-ai.streamlit.app"

        # KUNCI PERBAIKAN: Selalu ambil user_id yang konsisten dari session_state
        current_user = st.session_state.get("user_id") or st.session_state.get("current_user", "default_user")
        selected_templates = st.session_state.get("selected_templates", ["template01"])

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
                                    user_id=current_user
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
                            user_id=current_user
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
            # MODUL CSV MULTI-TEMPLATE & BROADCAST LINK WHATSAPP
            # =========================================================
            if is_session_active:
                st.markdown("---")
                st.markdown("### 📋 Multi-Template Guest List (Upload CSV per Template)")
                st.info(f"Anda saat ini mengaktifkan **{len(selected_templates)} Template**: `{', '.join(selected_templates)}`. "
                        f"Unggah file CSV (kolom **Nama**) untuk masing-masing template agar tautan undangan secara otomatis mengarah pada desain template yang diinginkan.")

                default_narration = "Tanpa mengurangi rasa hormat, kami mengundang Bapak/Ibu/Saudara/i untuk menghadiri acara pernikahan kami. Berikut link undangan digital:\n{link_undangan}\n\nMerupakan suatu kehormatan dan kebahagiaan bagi kami apabila Bapak/Ibu/Saudara/i berkenan hadir."
                
                custom_narration = st.text_area("Modifikasi Narasi / Pesan WhatsApp:", value=default_narration, height=120)
                st.caption("Gunakan `{link_undangan}` di dalam teks untuk menempatkan tautan undangan secara otomatis.")

                # Tab untuk membagi tempat unggah CSV per template
                template_tabs = st.tabs([f"🎨 {tpl}" for tpl in selected_templates])
                all_generated_links = []

                for idx, tpl_name in enumerate(selected_templates):
                    with template_tabs[idx]:
                        st.markdown(f"#### Upload Tamu Khusus **{tpl_name}**")
                        uploaded_csv = st.file_uploader(
                            f"Upload File Daftar Tamu (.csv) - [{tpl_name}]", 
                            type=["csv"], 
                            key=f"csv_uploader_{tpl_name}"
                        )

                        if uploaded_csv is not None:
                            try:
                                df_guests = pd.read_csv(uploaded_csv)
                                if 'Nama' not in df_guests.columns:
                                    st.error("⚠️ File CSV harus memiliki kolom dengan header bernama **Nama**.")
                                else:
                                    st.success(f"✅ Berhasil memuat {len(df_guests)} data tamu untuk **{tpl_name}**.")
                                    
                                    tpl_links = []
                                    for _, row in df_guests.iterrows():
                                        guest_n = str(row['Nama']).strip()
                                        link_item = f"{base_app_url}/?to={urllib.parse.quote(guest_n)}&user_id={current_user}&tpl={tpl_name}"
                                        message_text = custom_narration.replace("{link_undangan}", link_item)
                                        
                                        link_data = {
                                            "Nama Tamu": guest_n,
                                            "Template": tpl_name,
                                            "Link Undangan": link_item,
                                            "Format Pesan WhatsApp": message_text
                                        }
                                        tpl_links.append(link_data)
                                        all_generated_links.append(link_data)

                                    df_result = pd.DataFrame(tpl_links)
                                    st.dataframe(df_result, use_container_width=True, hide_index=True)

                                    csv_output = df_result.to_csv(index=False).encode('utf-8')
                                    st.download_button(
                                        label=f"📥 Download Link [{tpl_name}] (CSV)",
                                        data=csv_output,
                                        file_name=f"link_{tpl_name}_{current_user}.csv",
                                        mime="text/csv",
                                        key=f"dl_btn_{tpl_name}"
                                    )
                            except Exception as e:
                                st.error(f"Gagal memproses file CSV untuk {tpl_name}: {e}")

                        st.markdown("---")
                        st.markdown(f"#### ✍️ Generate Link Satuan untuk **{tpl_name}**:")
                        single_guest = st.text_input(f"Nama Tamu Satuan ({tpl_name})", "Bapak Budi & Keluarga", key=f"single_guest_{tpl_name}")
                        if single_guest:
                            single_link = f"{base_app_url}/?to={urllib.parse.quote(single_guest)}&user_id={current_user}&tpl={tpl_name}"
                            st.code(single_link, language="markdown")

                # REKAPITULASI MASTER GABUNGAN SELURUH TEMPLATE
                if all_generated_links:
                    st.markdown("---")
                    st.markdown("### 📦 Rekapitulasi Master Link Undangan (Semua Template)")
                    df_all = pd.DataFrame(all_generated_links)
                    st.dataframe(df_all, use_container_width=True, hide_index=True)

                    master_csv = df_all.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="🚀 Download Master CSV Gabungan (Semua Tamu & Template)",
                        data=master_csv,
                        file_name=f"MASTER_link_undangan_all_templates_{current_user}.csv",
                        mime="text/csv",
                        type="primary"
                    )

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
