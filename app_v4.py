from dotenv import load_dotenv
load_dotenv()

import os
import json
import time
import base64
import urllib.parse
import pandas as pd
import streamlit as st
from jinja2 import Template
from google import genai
from groq import Groq

# File JSON lokal untuk menyimpan data RSVP sementara
RSVP_FILE = "rsvp_data.json"

def load_rsvp_data():
    if os.path.exists(RSVP_FILE):
        try:
            with open(RSVP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_rsvp_data(data_list):
    with open(RSVP_FILE, "w", encoding="utf-8") as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)

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

    if not GEMINI_KEY and "GEMINI_API_KEY" in st.secrets:
        GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
    if not GROQ_KEY and "GROQ_API_KEY" in st.secrets:
        GROQ_KEY = st.secrets["GROQ_API_KEY"]

    if GEMINI_KEY and len(GEMINI_KEY) > 10:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                gemini_client = genai.Client(api_key=GEMINI_KEY)
                response = gemini_client.models.generate_content(
                    model='gemini-3.8-flash',
                    contents=prompt
                )
                if response and response.text:
                    clean_res = response.text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(clean_res)
                    return data, "Google Gemini (gemini-3.8-flash)"
            except Exception as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(1.5 * (attempt + 1))
                else:
                    break

    if GROQ_KEY and len(GROQ_KEY) > 10:
        groq_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-coder-32b"]
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
                except Exception:
                    continue
        except Exception as e:
            print(f"[DEBUG GROQ ERROR]: {e}")

    default_data = {
        "quote": f"Dua hati, satu cinta, menyatu dalam janji suci pernikahan {groom_name} & {bride_name}.",
        "theme_bg": "bg-slate-900",
        "theme_card_bg": "bg-slate-800",
        "theme_text": "text-amber-100"
    }
    return default_data, "Default Static Fallback"


# ---------------------------------------------------------
# UI STREAMLIT & LAYOUT UTAMA
# ---------------------------------------------------------
st.set_page_config(page_title="Wedding AI Generator", layout="wide")

st.title("💍 Wedding AI Invitation Generator")

# TAB NAVIGASI DASBOARD
tab_design, tab_broadcast, tab_analytics = st.tabs([
    "🎨 TAHAP 1: Desain & Musik Undangan", 
    "🚀 TAHAP 2: Upload Tamu & Redaksi WA",
    "📊 TAHAP 3: Monitoring RSVP & Buku Tamu"
])

# --- TAHAP 1: DESAIN ---
with tab_design:
    col_form, col_preview = st.columns([1, 1])

    with col_form:
        st.subheader("📋 1. Informasi Pasangan & Acara")
        groom_name = st.text_input("Nama Mempelai Pria", "Budi")
        bride_name = st.text_input("Nama Mempelai Wanita", "Siti")
        theme_choice = st.selectbox("Tema Visual AI", ["Rustic Elegance", "Modern Dark", "Gold Luxury", "Floral Romantic"])
        
        event_date = st.date_input("Tanggal Acara")
        event_location = st.text_input("Lokasi Acara", "Gedung Cendrawasih, Jakarta")
        maps_url = st.text_input("URL Google Maps Lokasi", "https://maps.google.com")
        bank_info = st.text_input("Informasi Amplop Digital / Bank", "BCA 123456789 a.n Budi")

        st.markdown("---")
        st.subheader("🖼️ 2. Galeri Foto Pasangan")
        uploaded_photos = st.file_uploader("Upload Foto Pasangan (Multi-upload)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
        default_photo_url = st.text_input("Atau URL Foto Sampul Utama", "https://images.unsplash.com/photo-1519741497674-611481863552")

        st.markdown("---")
        st.subheader("🎵 3. Background Music Player")
        music_option = st.radio("Sumber Musik Background:", ["Preset Musik", "Upload File MP3", "URL MP3 Eksternal"])
        
        final_music_url = ""
        if music_option == "Preset Musik":
            preset_choice = st.selectbox("Pilih Lagu Preset:", ["Acoustic Romantic (Instrumental)", "Piano Marriage D'Amour", "Violin Modern Love"])
            preset_urls = {
                "Acoustic Romantic (Instrumental)": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "Piano Marriage D'Amour": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
                "Violin Modern Love": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3"
            }
            final_music_url = preset_urls[preset_choice]
        elif music_option == "Upload File MP3":
            uploaded_audio = st.file_uploader("Upload Musik Latar (MP3/WAV/OGG)", type=["mp3", "wav", "ogg"])
            if uploaded_audio:
                final_music_url = file_to_base64(uploaded_audio)
                st.success("✅ File musik berhasil dimuat!")
        else:
            final_music_url = st.text_input("Masukkan Direct URL File MP3", "")

        st.markdown("---")
        test_guest_name = st.text_input("Nama Tamu Uji Coba (Untuk Preview)", "Budi Sudarsono")
        btn_generate = st.button("🚀 Generate & Kunci Desain AI", type="primary", use_container_width=True)

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

            st.session_state["design_ready"] = True
            st.session_state["groom_name"] = groom_name
            st.session_state["bride_name"] = bride_name

            try:
                with open("template.html", "r", encoding="utf-8") as f:
                    template_content = f.read()

                jinja_template = Template(template_content)
                rendered_html = jinja_template.render(
                    groom_name=groom_name,
                    bride_name=bride_name,
                    quote_text=ai_data.get("quote"),
                    event_date=event_date.strftime("%d %B %Y"),
                    event_location=event_location,
                    maps_url=maps_url,
                    photo_url=gallery_photos[0],
                    gallery_photos=gallery_photos,
                    bank_info=bank_info,
                    music_url=final_music_url,
                    guest_name=test_guest_name,
                    theme_bg=ai_data.get("theme_bg", "bg-gray-900"),
                    theme_card_bg=ai_data.get("theme_card_bg", "bg-gray-800"),
                    theme_text=ai_data.get("theme_text", "text-white")
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


# --- TAHAP 2: UPLOAD TAMU & BROADCAST ---
with tab_broadcast:
    st.subheader("👥 Generasi Link & Redaksi WhatsApp Massal")

    if not st.session_state.get("design_ready", False):
        st.info("👈 Silakan selesaikan dan klik 'Generate & Kunci Desain AI' di **Tahap 1** terlebih dahulu.")
    else:
        # Default Base URL otomatis menyesuaikan jika di lokal
        default_base_url = "http://localhost:8501"
        base_url = st.text_input("Base URL Web Undangan Anda (Ganti jika sudah dikirim ke domain publik)", default_base_url)
        
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
            st.download_button(
                "📥 Download Rekap CSV (Lengkap dengan Redaksi Teks WA)",
                data=csv_data,
                file_name="rekap_redaksi_undangan_wa.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )


# --- TAHAP 3: MONITORING RSVP & BUKU TAMU ---
with tab_analytics:
    st.subheader("📊 Monitoring Konfirmasi Kehadiran (RSVP) & Doa Tamu")
    
    # Form Tambah Data Simulasi Manual / Baca File
    rsvp_list = load_rsvp_data()

    if not rsvp_list:
        st.info("Belum ada data RSVP masuk dari tamu undangan.")
    else:
        df_rsvp = pd.DataFrame(rsvp_list)
        
        # Stat Cards Summary
        total_respon = len(df_rsvp)
        total_hadir = len(df_rsvp[df_rsvp['Kehadiran'] == 'Hadir'])
        total_ragu = len(df_rsvp[df_rsvp['Kehadiran'] == 'Ragu-ragu'])
        total_absen = len(df_rsvp[df_rsvp['Kehadiran'] == 'Maaf, Tidak Bisa Hadir'])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Respon Tamu", total_respon)
        m2.metric("Pasti Hadir", total_hadir)
        m3.metric("Ragu-Ragu", total_ragu)
        m4.metric("Tidak Hadir", total_absen)

        st.markdown("---")
        st.markdown("**📋 Rekap Tabel Kehadiran & Ucapan Doa:**")
        st.dataframe(df_rsvp, use_container_width=True, hide_index=True)

        # Download Rekap RSVP Excel/CSV
        csv_rsvp = df_rsvp.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Hasil Rekap RSVP (CSV)", data=csv_rsvp, file_name="rekap_status_rsvp_tamu.csv", mime="text/csv")