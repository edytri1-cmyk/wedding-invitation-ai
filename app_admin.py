import os
import json
from datetime import datetime
import pandas as pd
import streamlit as st

# File JSON Database Lokal
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

st.set_page_config(page_title="Dashboard Admin - Wedding AI", layout="wide")

st.title("🔑 Dashboard Admin & Pemantauan Owner")

# Sederhana Login Admin
admin_pass = st.sidebar.text_input("Password Admin:", type="password")
if admin_pass != "owner123":  # Ubah password sesuai keinginan
    st.warning("⚠️ Silakan masukkan password admin di sidebar untuk mengakses dashboard.")
    st.stop()

st.sidebar.success("✅ Login Admin Berhasil")

# Menu Navigasi Admin dengan 4 Fitur Utama
admin_menu = st.sidebar.radio(
    "Pilih Menu Admin:", 
    [
        "💳 Dashboard Pendapatan", 
        "🔑 Aktivasi & Override Manual", 
        "📊 Statistik & Tren Kunjungan", 
        "💬 Live Helpdesk Chat"
    ]
)

# ---------------------------------------------------------
# MENU 1: DASHBOARD REKAP & MONITORING PENDAPATAN (REVENUE)
# ---------------------------------------------------------
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
        
        # Kalkulasi metrik pendapatan (Asumsi harga paket lisensi Rp 49.000)
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


# ---------------------------------------------------------
# MENU 2: FITUR OVERRIDE / AKTIVASI MANUAL DARURAT
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# MENU 3: STATISTIK PENGUNJUNG & TREN HARIAN
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# MENU 4: LIVE HELPDESK CHAT (ADMIN REPLY)
# ---------------------------------------------------------
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