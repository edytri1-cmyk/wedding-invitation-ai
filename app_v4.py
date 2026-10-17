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

# File JSON Database Lokal
RSVP_FILE = "rsvp_data.json"
ORDERS_FILE = "orders_data.json"
CHAT_FILE = "chat_messages.json"
STATS_FILE = "stats_visitors.json"

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


# ---------------------------------------------------------
# UI STREAMLIT & LAYOUT UTAMA (USER JOURNEY)
# ---------------------------------------------------------
st.set_page_config(page_title="Wedding AI Generator", layout="wide")

st.title("💍 Wedding AI Invitation Generator")

# Inisialisasi Session State
if "agreed_terms" not in st.session_state:
    st.session_state["agreed_terms"] = False

menu_steps = [
    "1️⃣ Penjelasan & Keamanan Data ➡️",
    "2️⃣ Desain & Preview Undangan ➡️",
    "3️⃣ Paket, Monetisasi & Broadcast ➡️",
    "4️⃣ Manajemen RSVP Tamu"
]

active_step = st.radio(
    "🧭 **Alur User Journey Aplikasi:**", 
    menu_steps, 
    horizontal=True,
    index=0
)

st.markdown("---")

# Cek validitas masa aktif kode aktivasi (30 hari)
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


# =========================================================
# TAHAP 1: Penjelasan & Keamanan Data
# =========================================================
if active_step == menu_steps[0]:
    st.subheader("📖 1. Panduan Aplikasi & Jaminan Keamanan Data")
    
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
        3. Lanjut ke **Tahap 3**: Lakukan pembayaran transfer, konfirmasi pembayaran, masukkan kode aktivasi yang dikirim admin via email untuk membuka akses penuh selama 30 hari.
        4. Lanjut ke **Tahap 4**: Pantau kehadiran tamu (RSVP) dan ucapan doa yang masuk ke buku tamu digital Anda.
        """)
    
    with col_info2:
        st.markdown("""
        ### 🔒 Jaminan Keamanan & Privasi Data
        * **Enkripsi Data:** Seluruh data pribadi dan foto dikelola secara aman dalam sesi pengguna.
        * **Kerahasiaan Kontak Tamu:** Data nama tamu yang Anda unggah dapat anda hapus setelah selesai.
        * **Kendali Penuh:** Anda memiliki kendali penuh untuk memperbarui data kapan saja.
        """)
    
    st.markdown("---")
    agreement = st.checkbox("Saya telah membaca, memahami penjelasan aplikasi, dan menyetujui syarat serta kebijakan keamanan data.", value=st.session_state["agreed_terms"])
    
    if agreement:
        st.session_state["agreed_terms"] = True
        st.success("✅ Anda telah menyetujui ketentuan. Silakan klik menu **'2️⃣ Desain & Preview Undangan'** di atas untuk melanjutkan.")
    else:
        st.session_state["agreed_terms"] = False
        st.warning("⚠️ Harap centang kotak persetujuan di atas untuk melanjutkan ke tahap berikutnya.")


# =========================================================
# TAHAP 2: Data Wedding, Upload Foto, Tema, Backsound & Preview
# =========================================================
elif active_step == menu_steps[1]:
        if not st.session_state.get("agreed_terms", False):
            st.warning("⚠️ Mohon selesaikan dan setujui Syarat & Ketentuan di **Tahap 1** terlebih dahulu.")
        else:
            st.subheader("🎨 2. Data Pernikahan, Tema Visual, Musik & Preview Undangan")
            
            col_form, col_preview = st.columns([1, 1])

            with col_form:
                st.subheader("📋 Informasi Pasangan & Acara")
                
                if is_session_active:
                    st.info("🔒 **Mode Terkunci:** Lisensi Anda aktif. Seluruh form isian dan pengaturan desain dikunci untuk menjaga stabilitas undangan yang sudah disebar.")

                groom_name = st.text_input("Nama Mempelai Pria", "Budi", disabled=is_session_active)
                bride_name = st.text_input("Nama Mempelai Wanita", "Siti", disabled=is_session_active)
                theme_choice = st.selectbox("Tema Visual AI", ["Rustic Elegance", "Modern Dark", "Gold Luxury", "Floral Romantic"], disabled=is_session_active)
                
                event_date = st.date_input("Tanggal Acara", disabled=is_session_active)
                event_day = st.text_input("Hari Pernikahan", "Sabtu", disabled=is_session_active)
                event_time = st.text_input("Waktu / Jam Pernikahan", "11.00 - 13.00 WIB", disabled=is_session_active)
                event_location = st.text_input("Lokasi Acara", "Gedung Cendrawasih, Jakarta", disabled=is_session_active)
                maps_url = st.text_input("URL Google Maps Lokasi", "https://maps.google.com", disabled=is_session_active)
                bank_info = st.text_input("Informasi Amplop Digital / Bank", "BCA 123456789 a.n Budi", disabled=is_session_active)

                st.markdown("---")
                st.subheader("🖼️ Galeri Foto Pasangan")
                uploaded_photos = st.file_uploader("Upload Foto Pasangan (Multi-upload)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, disabled=is_session_active)
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
                test_guest_name = st.text_input("Nama Tamu Uji Coba (Untuk Preview)", "Budi Sudarsono")
                
                btn_generate = st.button("🚀 Generate & Kunci Desain AI", type="primary", use_container_width=True, disabled=is_session_active)

        if btn_generate:
            with st.spinner("Agent AI sedang merancang kata-kata & gaya visual..."):
                prompt = f"Buat 1 kalimat quote cinta indah tema {theme_choice} untuk {groom_name} & {bride_name}. Tentukan kelas Tailwind CSS theme_bg, theme_card_bg, theme_text. Format JSON."

                gallery_photos = []
                if uploaded_photos and len(uploaded_photos) > 0:
                    for photo in uploaded_photos:
                        b64_photo = file_to_base64(photo)
                        if b64_photo:
                            gallery_photos.append(b64_photo)
                else:
                    gallery_photos = [default_photo_url]

                ai_data, provider_used = generate_ai_content(prompt, theme_choice, groom_name, bride_name)

                st.info(f"API Provider yang merespons: {provider_used}")

                st.session_state["design_ready"] = True
                st.session_state["groom_name"] = groom_name
                st.session_state["bride_name"] = bride_name

                try:
                    template_content = """
                    <div class="{{theme_bg}} {{theme_text}} p-8 rounded-xl shadow-lg max-w-md mx-auto text-center font-sans">
                        <h1 class="text-3xl font-bold mb-2">{{groom_name}} & {{bride_name}}</h1>
                        <p class="italic text-sm mb-4">"{{quote_text}}"</p>
                        <hr class="my-4 border-gray-600">
                        <p class="font-semibold">{{event_date}}</p>
                        <p class="text-sm mb-4">{{event_location}}</p>
                        <img src="{{photo_url}}" class="rounded-lg mx-auto w-full h-64 object-cover mb-4">
                        <p class="text-xs">Kepada Yth. <b>{{guest_name}}</b></p>
                    </div>
                    """
                    if os.path.exists("template.html"):
                        with open("template.html", "r", encoding="utf-8") as f:
                            template_content = f.read()

                    jinja_template = Template(template_content)
                    rendered_html = jinja_template.render(
                        groom_name=groom_name,
                        bride_name=bride_name,
                        quote_text=ai_data.get("quote"),
                        event_date=event_date.strftime("%d %B %Y"),
                        event_day=event_day,
                        event_time=event_time,
                        event_location=event_location,
                        maps_url=maps_url,
                        photo_url=gallery_photos[0],
                        gallery_photos=gallery_photos,
                        bank_info=bank_info,
                        music_url=final_music_url,
                        guest_name=test_guest_name,
                        theme_bg=ai_data.get("theme_bg", "bg-slate-900"),
                        theme_card_bg=ai_data.get("theme_card_bg", "bg-slate-800"),
                        theme_text=ai_data.get("theme_text", "text-amber-100")
                    )

                    st.session_state["rendered_html"] = rendered_html
                    st.success(f"✅ Undangan Berhasil Dibuat (Diproses via {provider_used})!")
                except Exception as e:
                    st.error(f"Gagal merender template HTML: {e}")

        with col_preview:
            st.subheader("👁️ Pratinjau Tampilan Undangan")
            if "rendered_html" in st.session_state:
                st.components.v1.html(st.session_state["rendered_html"], height=750, scrolling=True)
            else:
                st.info("Atur form di sebelah kiri lalu klik 'Generate & Kunci Desain AI' untuk melihat pratinjau.")


# =========================================================
# TAHAP 3: Paket, Pembayaran Otomatis (Midtrans) & Broadcast
# =========================================================
elif active_step == menu_steps[2]:
    if not st.session_state.get("design_ready", False):
        st.warning("⚠️ Silakan selesaikan desain undangan di **Tahap 2** terlebih dahulu.")
    else:
        st.subheader("🚀 3. Redaksi WhatsApp, Link Tamu, & Pembayaran Otomatis")
        
        st.markdown("### 💳 Pembayaran Lisensi Akses 30 Hari (Otomatis via Midtrans)")
        st.info("💡 Sistem pembayaran menggunakan **Midtrans Sandbox (Uji Coba)**.")

        if is_session_active:
            st.success("🎉 **Layanan Aktif!** Lisensi Anda berlaku penuh (Maksimal 30 hari sejak aktivasi). Seluruh fitur tahap 3 dan 4 dapat digunakan.")
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
                            # Ambil kunci dari st.secrets atau fallback ke variabel lokal
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
            st.markdown("#### 🔑 Aktivasi Otomatis / Manual Kode Unik")
            
            code_input = st.text_input("Masukkan Kode Aktivasi / Order ID")
            if st.button("Aktivasi Sekarang"):
                if code_input.strip():
                    orders_db[code_input] = {
                        "name": "Simulasi Pembeli",
                        "status": "ACTIVATED",
                        "activated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    save_json(ORDERS_FILE, orders_db)
                    
                    st.session_state["activated_code_input"] = code_input
                    st.success("🎉 Simulasi Aktivasi Berhasil! Halaman akan dimuat ulang.")
                    st.rerun()
                else:
                    st.error("❌ Masukkan kode yang valid.")

        st.markdown("---")
        
        # Broadcast & Link Tamu
        default_base_url = "https://share.streamlit.io" # Sesuaikan jika sudah di-deploy
        base_url = st.text_input("Base URL Web Undangan Anda", default_base_url)
        
        custom_template = st.text_area(
            "Template Redaksi Pesan WhatsApp",
            "Tanpa mengurangi rasa hormat, kami mengundang Bapak/Ibu/Saudara/i *[NAMA_TAMU]* untuk menghadiri acara pernikahan kami.\n\nDetail undangan dapat diakses pada link berikut:\n[LINK_UNDANGAN]\n\nMerupakan suatu kehormatan bagi kami apabila Bapak/Ibu/Saudara/i berkenan hadir.\nTerima kasih.",
            height=110
        )

        st.markdown("---")
        input_method = st.radio("Metode Input Daftar Tamu:", ["Upload File CSV (Rekomendasi Massal)", "Ketik / Paste Teks Manual"], horizontal=True)

        guest_list = []
        if input_method == "Upload File CSV (Rekomendasi Massal)":
            uploaded_csv = st.file_uploader("Upload File CSV (Format: Kolom 'Nama')", type=["csv"])
            if uploaded_csv is not None:
                try:
                    df_input = pd.read_csv(uploaded_csv)
                    col_name = [c for c in df_input.columns if 'nama' in c.lower()]
                    guest_list = df_input[col_name[0]].dropna().astype(str).tolist() if col_name else df_input.iloc[:, 0].dropna().astype(str).tolist()
                    st.success(f"✅ Berhasil memuat {len(guest_list)} nama tamu!")
                except Exception as e:
                    st.error(f"Gagal membaca file CSV: {e}")
        else:
            raw_guests = st.text_area("Masukkan Nama Tamu (Satu Nama Per Baris)", "Budi Sudarsono\nKeluarga Besar Ahmad\nDr. Hendra & Istri", height=120)
            guest_list = [g.strip() for g in raw_guests.split("\n") if g.strip()]

        if guest_list:
            st.markdown("---")
            table_data = []
            for idx, guest in enumerate(guest_list, 1):
                encoded_name = urllib.parse.quote(guest)
                guest_link = f"{base_url}?to={encoded_name}"
                wa_redaksi = custom_template.replace("[NAMA_TAMU]", guest).replace("[LINK_UNDANGAN]", guest_link)
                
                table_data.append({
                    "No": idx,
                    "Nama Tamu": guest,
                    "Link Khusus": guest_link,
                    "Redaksi WhatsApp Ready": wa_redaksi
                })

            df_result = pd.DataFrame(table_data)

            st.dataframe(
                df_result,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Link Khusus": st.column_config.LinkColumn("Link Undangan (Klik/Copy)"),
                    "Redaksi WhatsApp Ready": st.column_config.TextColumn("Redaksi WA", width="large")
                }
            )

            csv_data = df_result.to_csv(index=False).encode('utf-8')
            
            if is_session_active:
                st.download_button(
                    "📥 Download Rekap CSV (Lengkap dengan Redaksi Teks WA)",
                    data=csv_data,
                    file_name="rekap_redaksi_undangan_wa.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )
            else:
                st.warning("🔒 Tombol download terkunci. Selesaikan pembayaran untuk mengunduh rekap CSV.")


# =========================================================
# TAHAP 4: Manajemen RSVP & Buku Tamu
# =========================================================
elif active_step == menu_steps[3]:
    st.subheader("📊 4. Manajemen RSVP & Buku Tamu Digital")
    
    if not is_session_active:
        st.error("🔒 **Menu Terkunci!** Manajemen RSVP dan pemantauan tamu digital hanya aktif jika Anda telah memasukkan kode aktivasi layanan pada **Tahap 3**.")
    else:
        rsvp_list = load_json(RSVP_FILE, [])

        if not rsvp_list:
            st.info("Belum ada data RSVP masuk dari tamu undangan.")
        else:
            df_rsvp = pd.DataFrame(rsvp_list)
            
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
            st.download_button("📥 Download Hasil Rekap RSVP (CSV)", data=csv_rsvp, file_name="rekap_status_rsvp_tamu.csv", mime="text/csv")


# =========================================================
# LIVE HELPDESK CHAT (DI SIDEBAR)
# =========================================================
if "user_session_id" not in st.session_state:
    st.session_state["user_session_id"] = f"USER-{str(uuid.uuid4())[:8]}"

current_user_session = st.session_state["user_session_id"]

user_msg = st.sidebar.text_input("Tulis Pesan ke Admin:", key="user_chat_input")
if st.sidebar.button("Kirim Pesan", key="btn_send_user_chat"):
    if user_msg.strip():
        chat_history = load_json(CHAT_FILE, [])
        chat_history.append({
            "session_id": current_user_session,
            "sender": "User",
            "message": user_msg,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        save_json(CHAT_FILE, chat_history)
        st.sidebar.success("Pesan terkirim!")
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("**Riwayat Percakapan Anda:**")

@st.fragment(run_every=3)
def render_user_chat_history():
    chat_history = load_json(CHAT_FILE, [])
    my_chats = [c for c in chat_history if c.get("session_id") == current_user_session]
    
    chat_container = st.sidebar.container(height=250)
    with chat_container:
        if not my_chats:
            st.info("Belum ada pesan.")
        else:
            for chat in my_chats:
                sender_label = "👤 **Anda**" if chat['sender'] == "User" else "🛠️ **Admin**"
                st.markdown(f"{sender_label} *({chat['time']})*:\n{chat['message']}")
                st.markdown("---")

render_user_chat_history()
