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
                # Pulihkan sesi pengguna
                st.session_state["user_id"] = order_id  
                st.session_state["activated_code_input"] = order_id
                st.session_state["user_token"] = url_token
                
                st.session_state["is_session_active"] = True  
                st.session_state["agreed_terms"] = True       
                st.session_state["design_ready"] = True       
                
                # Arahkan langsung ke Tahap 3
                st.session_state["active_step"] = "3️⃣ Buat Link Undangan"
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
        st.subheader("📊 Statistik Pengunjung & Tren Harian")
        st.info("Memantau jumlah kunjungan harian ke aplikasi utama undangan digital.")
        
        stats_data = load_json(STATS_FILE, {})
        if not stats_data:
            st.info("Belum ada data kunjungan tercatat.")
        else:
            df_stats = pd.DataFrame(list(stats_data.items()), columns=["Tanggal", "Jumlah Pengunjung"])
            df_stats = df_stats.sort_values(by="Tanggal", ascending=False)
            
            total_visitors = df_stats["Jumlah Pengunjung"].sum()
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_visitors = stats_data.get(today_str, 0)
            
            col_s1, col_s2 = st.columns(2)
            col_s1.metric("Total Kunjungan Kumulatif", total_visitors)
            col_s2.metric("Kunjungan Hari Ini", today_visitors)
            
            st.markdown("---")
            st.dataframe(df_stats, use_container_width=True, hide_index=True)
            
            st.markdown("### 📈 Grafik Tren Pengunjung Harian")
            st.bar_chart(df_stats.set_index("Tanggal"))

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
    st.title("💍 Wedding AI Invitation Generator")

    if "agreed_terms" not in st.session_state:
        st.session_state["agreed_terms"] = False

    menu_steps = [
        "1️⃣ Panduan Aplikasi ➡️",
        "2️⃣ Desain & Preview Undangan ➡️",
        "3️⃣ Buat Link Undangan ➡️",
        "4️⃣ Manajemen RSVP Tamu"
    ]

    active_step = st.radio(
        "🧭 **Alur Aplikasi:**", 
        menu_steps, 
        horizontal=True,
        index=0
    )

    st.markdown("---")

    orders_db = load_json(ORDERS_FILE, {})
    activated_code = st.session_state.get("activated_code_input", "")
    is_session_active = False

    if activated_code in orders_db:
        order_info = orders_db[activated_code]
        if order_info.get("status") == "ACTIVATED":
            activated_date = datetime.strptime(order_info["activated_at"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - activated_date <= timedelta(days=30):
                is_session_active = True
            else:
                st.sidebar.error("⚠️ Masa aktif kode aktivasi Anda telah melebihi 30 hari dan telah kedaluwarsa.")

    # TAHAP 1
    if active_step == menu_steps[0]:
        st.subheader("📖 1. Panduan Aplikasi")
        
        col_info1, col_info2 = st.columns(2)
        with col_info1:
            st.markdown("""
            ### 🌟 Tentang Aplikasi
            **Wedding AI Generator** adalah platform pembuatan undangan pernikahan digital cerdas berbasis AI. 
            Anda dapat mendesain undangan impian, mengatur musik latar belakang, menyebar undangan secara massal ke WhatsApp, 
            serta memantau kehadiran tamu (RSVP) secara real-time.
            
            ### 🚀 Cara Penggunaan:
            1. **Pahami & Setujui** Syarat dan Ketentuan di halaman ini.
            2. Lanjut ke **Tahap 2**: Isi data mempelai, upload foto galeri, pilih tema AI, dan atur backsound musik. Generate undangan dan lihat preview-nya secara langsung.
            3. Lanjut ke **Tahap 3**: Lakukan pembayaran , konfirmasi pembayaran, masukkan kode aktivasi yang dikirim admin via email untuk membuka akses penuh selama 30 hari.
            4. Lanjut ke **Tahap 4**: Pantau kehadiran tamu (RSVP) dan ucapan doa yang masuk ke buku tamu digital Anda.
            """)
        
        with col_info2:
            st.markdown("""
            ### 🔒 Jaminan Keamanan & Privasi Data
            * **Enkripsi Data:** Seluruh data pribadi dan foto tidak disimpan di server.
            * **Kerahasiaan Kontak Tamu:** Data nama tamu yang Anda Unggah dijamin aman.
            * **Kendali Penuh:** Anda memiliki kendali penuh untuk memperbarui data kapan saja.
            """)
        
        st.markdown("---")
        agreement = st.checkbox("Saya telah membaca dan menyetujui syarat serta kebijakan keamanan data.", value=st.session_state["agreed_terms"])
        
        if agreement:
            st.session_state["agreed_terms"] = True
            st.success("✅ Anda telah menyetujui ketentuan. Silakan klik menu **'2️⃣ Desain & Preview Undangan'** di atas untuk melanjutkan.")
        else:
            st.session_state["agreed_terms"] = False
            st.warning("⚠️ Harap centang kotak persetujuan di atas untuk melanjutkan ke tahap berikutnya.")

# TAHAP 2
    elif active_step == menu_steps[1]:
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
                    "✨ Chic & Modern Gold", 
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
                
                # List untuk menyimpan data foto beserta caption-nya
                gallery_data = []
                
                # Validasi jumlah dan ukuran file secara manual di Python
                if uploaded_photos:
                    if len(uploaded_photos) > 5:
                        st.error("⚠️ Maksimal hanya boleh mengupload 5 foto!")
                    else:
                        has_oversized_file = False
                        for photo in uploaded_photos:
                            if photo.size > 2 * 1024 * 1024: # Batasan 2MB dalam bytes
                                st.error(f"⚠️ File {photo.name} terlalu besar! Harap upload foto di bawah 2MB.")
                                has_oversized_file = True
                        
                        # Jika semua file ukurannya aman, tampilkan kolom input caption
                        if not has_oversized_file:
                            st.markdown("### ✍️ Tulis Keterangan / Cerita Foto:")
                            
                            temp_gallery = []
                            for i, photo in enumerate(uploaded_photos):
                                caption = st.text_input(
                                    f"Cerita untuk Foto {i+1} ({photo.name})",
                                    placeholder="Contoh: Momen saat liburan pertama di luar negeri...",
                                    key=f"caption_{i}"
                                )
                                
                                # Konversi ke Base64
                                bytes_data = photo.getvalue()
                                base64_encoded = base64.b64encode(bytes_data).decode("utf-8")
                                img_src = f"data:image/{photo.type.split('/')[-1]};base64,{base64_encoded}"
                                
                                temp_gallery.append({
                                    "photo": img_src,
                                    "caption": caption
                                })
    
                            # Simpan ke session_state agar terbawa saat tombol Generate diklik
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

                        # Ambil data gallery yang berisi foto dan caption dari session_state
                        gallery_photos = []
                        raw_gallery = st.session_state.get('gallery_photos', [])
                        
                        if raw_gallery and len(raw_gallery) > 0:
                            gallery_photos = raw_gallery
                        else:
                            # Fallback jika tidak ada foto yang di-upload
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
                                # Data Akad
                                akad_date=akad_date.strftime("%d %B %Y"),
                                raw_event_date=akad_date.strftime("%Y-%m-%d"),
                                akad_day=akad_day,
                                akad_time=akad_time,
                                akad_location=akad_location,
                                akad_maps_url=akad_maps_url,
                                # Data Resepsi
                                resep_date=resep_date.strftime("%d %B %Y"),
                                resep_day=resep_day,
                                resep_time=resep_time,
                                resep_location=resep_location,
                                resep_maps_url=resep_maps_url,
                                # Turut Mengundang
                                turut_mengundang=turut_mengundang,
                                # Lainnya (Mengirim list dictionary yang berisi foto & caption)
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

# TAHAP 3
    elif active_step == menu_steps[2]:
        # Tentukan base URL aktif saat ini (bisa diubah ke undanganku.com nanti saat deploy ke VPS Rumahweb)
        base_app_url = "https://wedding-invitation-ai.streamlit.app"

        if not st.session_state.get("design_ready", False):
            st.warning("⚠️ Silakan selesaikan desain undangan di **Tahap 2** terlebih dahulu.")
        else:
            st.subheader("🚀 3. Redaksi WhatsApp, Link Tamu, & Pembayaran Otomatis")
            
            st.markdown("### 💳 Pembayaran Lisensi Akses 30 Hari (Otomatis via Midtrans)")
            st.info("💡 Sistem pembayaran menggunakan **Midtrans Sandbox (Uji Coba)**.")

            if is_session_active:
                st.success("🎉 **Layanan Aktif!** Lisensi Anda berlaku penuh (Maksimal 30 hari sejak aktivasi). Seluruh fitur tahap 3 dan 4 dapat digunakan.")
                
                # Menampilkan link token cadangan sesuai domain aktif saat ini
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
                        # Generate token unik untuk pemulihan sesi (anti-putus)
                        user_token = str(uuid.uuid4())
                        
                        orders_db[code_input] = {
                            "name": "Simulasi Pembeli",
                            "status": "ACTIVATED",
                            "token": user_token,
                            "activated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        save_json(ORDERS_FILE, orders_db)
                        
                        st.session_state["activated_code_input"] = code_input
                        st.session_state["user_token"] = user_token
                        
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
                
                # Template narasi default
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
                                # Link unik yang membawa parameter 'to' dan 'user_id'
                                link_item = f"{base_app_url}?to={urllib.parse.quote(guest_n)}&user_id={current_user}"
                                message_text = custom_narration.replace("{link_undangan}", link_item)
                                
                                # Mengubah kolom ke-3 menjadi plain text narasi undangan
                                
                                generated_links.append({
                                    "Nama Tamu": guest_n,
                                    "Link Undangan": link_item,
                                    "Format Pesan WhatsApp": message_text
                                })
                            
                            df_result = pd.DataFrame(generated_links)
                            st.markdown("#### 📊 Hasil Generate Link Undangan Unik:")
                            st.dataframe(df_result, use_container_width=True, hide_index=True)

                            # Tombol Download CSV Hasil Generate
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
                    # Generator Manual Satuan (Opsional jika tidak upload CSV)
                    st.markdown("#### ✍️ Atau Generate Link untuk 1 Tamu:")
                    single_guest = st.text_input("Nama Tamu Satuan", "Bapak Budi & Keluarga")
                    if single_guest:
                        single_link = f"https://wedding-invitation-ai.streamlit.app/?to={urllib.parse.quote(single_guest)}&user_id={current_user}"
                        
                        st.markdown("Link Undangan Satuan:")
                        # Menggunakan st.code agar otomatis ada tombol copy di pojok kanan atas
                        st.code(single_link, language="markdown")

    # TAHAP 4
    elif active_step == menu_steps[3]:
        st.subheader("📊 4. Manajemen RSVP & Buku Tamu Digital")
        
        if not is_session_active:
            st.error("🔒 **Menu Terkunci!** Manajemen RSVP dan pemantauan tamu digital hanya aktif jika Anda telah memasukkan kode aktivasi layanan pada **Tahap 3**.")
        else:
            # Masukkan URL CSV publik Google Sheet Anda di sini
            GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSsaN2n7MKVozzpZ-61okbgxjp8JE1CgA6HG2TUEn2AMqBDFOJ3vdtHeTlJDngnlIFa7P3zgf1ppzvX/pub?gid=0&single=true&output=csv"
            
            if "MASUKKAN_URL" in GOOGLE_SHEET_CSV_URL:
                st.warning("⚠️ URL CSV Google Sheet belum dikonfigurasi di Tahap 4 app.py.")
            else:
                try:
                    # Baca langsung dari Google Sheet CSV
                    df_all = pd.read_csv(GOOGLE_SHEET_CSV_URL)
                    
                    # Bersihkan spasi pada nama kolom
                    df_all.columns = df_all.columns.str.strip()
                    
                    # Filter data berdasarkan User_ID sesi aktif secara Case-Insensitive
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
