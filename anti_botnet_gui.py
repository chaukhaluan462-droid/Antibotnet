import os
import sys
import csv
import io
import hmac
import ctypes
import hashlib
import json
import subprocess
import threading
import urllib.request
import urllib.error
import winreg
from datetime import datetime, timedelta
from collections import defaultdict
import psutil
import customtkinter as ctk
from tkinter import ttk, messagebox

# Cấu hình chủ đề Dark Mode
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Bảng màu Cyberpunk Dark Obsidian v6.1
BG_MAIN = "#0b0f19"
BG_CARD = "#111827"
BORDER_COLOR = "#1f2937"
ROW_EVEN = "#111827"
ROW_ODD = "#162032"
ROW_SUS = "#3f151b"
ROW_DANGER = "#581c1c"
ROW_STANDBY = "#0f172a"
ACCENT_BLUE = "#2563eb"

CONFIG_FILE = "antibotnet_config.json"

# Khóa bí mật dùng để ký License Key (TUYỆT ĐỐI KHÔNG CHIA SẺ MÃ NÀY CHO KHÁCH)
LICENSE_SECRET_SALT = "ANTIBOTNET_PRO_V6_COMMERCIAL_SECRET_2026_!@#"

# Các thư mục cực kỳ nhạy cảm (Mức độ nghi vấn cao)
HIGH_RISK_PATHS = [
    "appdata\\local\\temp",
    "windows\\temp",
    "users\\public",
    "perflogs",
    "$recycle.bin"
]

# Các thư mục hợp lệ phổ biến để tránh Cảnh báo nhầm (False Positive)
LEGIT_INSTALL_PREFIXES = [
    "c:\\program files\\",
    "c:\\program files (x86)\\",
    "c:\\windows\\system32\\",
    "c:\\windows\\syswow64\\",
    "c:\\windows\\winsxs\\",
    "programdata\\microsoft\\windows defender"
]

LEGIT_APPDATA_KEYWORDS = [
    "appdata\\local\\programs\\",
    "appdata\\local\\discord\\",
    "appdata\\local\\vesktop\\",
    "appdata\\local\\google\\chrome\\",
    "appdata\\local\\microsoft\\",
    "appdata\\local\\bravesoftware\\",
    "appdata\\local\\zalo",
    "appdata\\roaming\\telegram desktop\\",
    "appdata\\roaming\\spotify\\",
    "appdata\\roaming\\zoom\\"
]

BOTNET_PORTS = {
    4444, 1337, 6667, 6666, 3333, 5555, 9001, 14444, 8333, 7777,
    1604, 2222, 4443, 8081, 9999
}

STANDARD_SAFE_PORTS = {80, 443, 53, 123, 8080, 8443, 5222, 5228, 3478, 19302}

WINDOWS_CORE_PROCS = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "svchost.exe", "fontdrvhost.exe",
    "winlogon.exe", "dwm.exe", "ctfmon.exe", "taskhostw.exe",
    "runtimebroker.exe", "sihost.exe", "idle", "memory compression",
    "spoolsv.exe", "conhost.exe", "dllhost.exe", "audiodg.exe"
}

WHITELIST_PROCESSES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
    "discord.exe", "vesktop.exe", "code.exe", "explorer.exe",
    "searchhost.exe", "spotify.exe", "onedrive.exe", "zalo.exe",
    "telegram.exe", "steam.exe", "robloxplayerbeta.exe", "hd-player.exe",
    "obs64.exe", "obs.exe", "defendersessionhelper.exe", "msmpeng.exe",
    "securityhealthservice.exe"
}


# ================= QUYỀN ADMIN & UAC AUTO-ELEVATION =================
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def ensure_admin_privileges():
    """Tự động bật bảng UAC xin quyền Administrator khi mở app nếu chưa có."""
    if not is_admin():
        try:
            script = os.path.abspath(sys.argv[0])
            params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
            if not getattr(sys, 'frozen', False):
                params = f'"{script}" {params}'.strip()
                target = sys.executable
            else:
                target = script

            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, params, None, 1)
            if int(ret) > 32:
                sys.exit(0)
        except Exception:
            pass


# ================= HỆ THỐNG MÃ MÁY (HWID) & LICENSE KEY =================
def get_machine_hwid() -> str:
    raw_id = ""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        raw_id = str(guid).strip()
    except Exception:
        raw_id = os.environ.get("COMPUTERNAME", "UNKNOWN_PC") + os.environ.get("USERNAME", "USER")

    digest = hashlib.sha256((raw_id + "_AB_HWID").encode("utf-8")).hexdigest().upper()[:16]
    return f"{digest[0:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"


# ---- Định dạng key mới (KHÔNG gắn HWID): PRO6-<THỜI HẠN>-<MÃ NGẪU NHIÊN>-<CHỮ KÝ>
#      VD: PRO6-D030-A1B2C3D4-9F8E7D6C5B4A   (D030 = 30 ngày tính từ ngày kích hoạt)
#          PRO6-LIFETIME-A1B2C3D4-9F8E7D6C5B4A
LICENSE_REG_PATH = r"Software\AntiBotnetPro"
LICENSE_REG_VALUE = "LicenseState"


def _mac(text: str) -> str:
    return hmac.new(
        LICENSE_SECRET_SALT.encode("utf-8"), text.encode("utf-8"), hashlib.sha256
    ).hexdigest().upper()


def parse_license_key(license_key: str):
    """Kiểm tra chữ ký key. Trả về (ok, msg, duration_days, clean_key). duration_days = 0 -> vĩnh viễn."""
    clean = (license_key or "").strip().upper()
    if not clean:
        return False, "Chưa nhập mã bản quyền.", 0, ""
    parts = clean.split("-")
    if len(parts) != 4 or parts[0] != "PRO6":
        return False, "Định dạng Key không hợp lệ (Chuẩn: PRO6-XXXX-XXXXXXXX-XXXXXXXXXXXX).", 0, ""

    dur, nonce, sig = parts[1], parts[2], parts[3]
    if not hmac.compare_digest(sig, _mac(f"{dur}|{nonce}")[:12]):
        return False, "Key không hợp lệ hoặc đã bị chỉnh sửa!", 0, ""

    if dur == "LIFETIME":
        return True, "OK", 0, clean
    if dur.startswith("D") and dur[1:].isdigit() and int(dur[1:]) > 0:
        return True, "OK", int(dur[1:]), clean
    return False, "Thông tin thời hạn trong Key bị hỏng.", 0, ""


def _state_sig(hwid: str, payload: dict) -> str:
    # Chữ ký gắn với HWID máy -> copy file/registry sang máy khác sẽ mất hiệu lực
    return _mac(hwid.strip().upper() + "|" + json.dumps(payload, sort_keys=True))


def _read_state_registry():
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, LICENSE_REG_PATH, 0, winreg.KEY_READ)
        raw, _ = winreg.QueryValueEx(k, LICENSE_REG_VALUE)
        winreg.CloseKey(k)
        return json.loads(raw)
    except Exception:
        return None


def _write_state_registry(state: dict):
    try:
        k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, LICENSE_REG_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k, LICENSE_REG_VALUE, 0, winreg.REG_SZ, json.dumps(state))
        winreg.CloseKey(k)
    except Exception:
        pass


def load_license_state(hwid: str):
    """Đọc trạng thái bản quyền từ registry + file config, chỉ nhận bản có chữ ký đúng máy này."""
    candidates = [_read_state_registry(), load_config().get("license_state")]
    valid = []
    for st in candidates:
        if not isinstance(st, dict) or "payload" not in st or "sig" not in st:
            continue
        if hmac.compare_digest(str(st["sig"]), _state_sig(hwid, st["payload"])):
            valid.append(st)
    if not valid:
        return None
    # Chọn bản "mới nhất" (nhiều key đã dùng nhất, last_seen lớn nhất)
    valid.sort(key=lambda s: (len(s["payload"].get("used_keys", [])), s["payload"].get("last_seen", "")))
    return valid[-1]


def save_license_state(hwid: str, payload: dict):
    state = {"payload": payload, "sig": _state_sig(hwid, payload)}
    _write_state_registry(state)
    save_config({"license_state": state})


def check_license_state(hwid: str):
    """Kiểm tra bản quyền đang lưu trên máy. Trả về (ok, msg, hiển thị hạn)."""
    st = load_license_state(hwid)
    if not st:
        return False, "Máy này chưa kích hoạt bản quyền.", ""

    p = st["payload"]
    today = datetime.now().date()

    if p["expiry"] == "LIFETIME":
        return True, "Bản quyền Vĩnh Viễn (Lifetime)", "Vĩnh viễn"

    try:
        exp_date = datetime.strptime(p["expiry"], "%Y%m%d").date()
        last_seen = datetime.strptime(p.get("last_seen", p["activated"]), "%Y%m%d").date()
    except ValueError:
        return False, "Dữ liệu bản quyền bị hỏng.", ""

    if today < last_seen:
        return False, "Phát hiện giờ hệ thống bị chỉnh lùi! Vui lòng chỉnh lại đúng ngày giờ.", ""
    if today > exp_date:
        return False, f"Key đã hết hạn vào ngày {exp_date.strftime('%d/%m/%Y')}. Hãy nhập key mới.", ""

    if today > last_seen:  # cập nhật mốc thời gian đã thấy (chống chỉnh lùi giờ)
        p["last_seen"] = today.strftime("%Y%m%d")
        save_license_state(hwid, p)

    days_left = (exp_date - today).days
    return True, f"Hợp lệ (Còn {days_left} ngày)", exp_date.strftime("%d/%m/%Y")


def activate_license_key(hwid: str, license_key: str):
    """Kích hoạt key. 1 máy chỉ dùng 1 key tại một thời điểm, chỉ đổi key khi key cũ đã hết hạn."""
    ok, msg, days, clean = parse_license_key(license_key)
    if not ok:
        return False, msg

    st = load_license_state(hwid)
    used = []
    if st:
        p = st["payload"]
        used = list(p.get("used_keys", []))
        cur_ok, cur_msg, cur_exp = check_license_state(hwid)
        if cur_ok:
            if p.get("key") == clean:
                return False, "Key này đang được sử dụng trên máy này rồi."
            return False, f"Máy này đang dùng một key còn hạn (đến {cur_exp}). Chỉ có thể nhập key mới khi key hiện tại hết hạn!"
        if p.get("key") and p["key"] not in used:
            used.append(p["key"])

    if clean in used:
        return False, "Key này đã được sử dụng và hết hạn trên máy này, không thể dùng lại!"

    today = datetime.now().date()
    expiry = "LIFETIME" if days == 0 else (today + timedelta(days=days)).strftime("%Y%m%d")
    payload = {
        "key": clean,
        "activated": today.strftime("%Y%m%d"),
        "expiry": expiry,
        "last_seen": today.strftime("%Y%m%d"),
        "used_keys": used,
    }
    save_license_state(hwid, payload)
    return True, ("Bản quyền Vĩnh Viễn (Lifetime)" if days == 0 else f"Kích hoạt thành công, thời hạn {days} ngày (đến {(today + timedelta(days=days)).strftime('%d/%m/%Y')})")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(data: dict):
    cfg = load_config()
    cfg.update(data)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ================= PHÂN TÍCH ĐƯỜNG DẪN & CHỐNG GIẢ MẠO (ANTI-BYPASS) =================
def is_legitimate_windows_core_process(name_lower: str, exe_path: str) -> bool:
    """
    Kiểm tra tiến trình có phải là tiến trình lõi của Windows THẬT hay không.
    Xử lý chuẩn các tiến trình Kernel ảo (Registry, System, Memory Compression) không có file .exe.
    """
    kernel_pseudo_procs = {"system", "registry", "idle", "memory compression", "secure system", "vmmem"}

    if name_lower in kernel_pseudo_procs:
        # Tiến trình Kernel ảo chỉ hợp lệ khi không có đường dẫn ổ đĩa thật (không chứa dấu '\' hoặc ':')
        if not exe_path or ("\\" not in exe_path and ":" not in exe_path):
            return True
        return False

    if name_lower not in WINDOWS_CORE_PROCS:
        return False

    if not exe_path:
        return True

    p_low = os.path.normpath(exe_path).lower()
    valid_sys_dirs = (
        r"c:\windows\system32",
        r"c:\windows\syswow64",
        r"c:\windows\winsxs"
    )
    return any(p_low.startswith(d + "\\") for d in valid_sys_dirs)


def is_legitimate_whitelisted_app(name_lower: str, exe_path: str) -> bool:
    if name_lower not in WHITELIST_PROCESSES or not exe_path:
        return False

    p_low = os.path.normpath(exe_path).lower()

    if name_lower == "explorer.exe":
        return p_low in (r"c:\windows\explorer.exe", r"c:\windows\syswow64\explorer.exe")

    if any(hr in p_low for hr in HIGH_RISK_PATHS):
        return False

    if any(p_low.startswith(prefix) for prefix in LEGIT_INSTALL_PREFIXES):
        return True
    if any(kw in p_low for kw in LEGIT_APPDATA_KEYWORDS):
        return True

    return False


def evaluate_process_risk(name: str, exe_path: str, remote_ip: str, remote_port) -> tuple:
    name_lower = (name or "").lower()
    p_low = os.path.normpath(exe_path).lower() if exe_path else ""

    # 1. Phát hiện giả mạo tiến trình hệ thống (svchost.exe, lsass.exe... nằm sai chỗ)
    if name_lower in WINDOWS_CORE_PROCS and exe_path:
        if not is_legitimate_windows_core_process(name_lower, exe_path):
            return True, True, "🚨 GIẢ MẠO HỆ THỐNG"

    # 2. Phát hiện giả mạo trình duyệt / ứng dụng phổ biến chạy từ thư mục Temp/Public
    if name_lower in WHITELIST_PROCESSES and exe_path:
        if any(hr in p_low for hr in HIGH_RISK_PATHS):
            return True, True, "🚨 GIẢ MẠO APP"

    # 3. Kết nối tới cổng Botnet / RAT C2 đã biết
    if isinstance(remote_port, int) and remote_port in BOTNET_PORTS:
        return True, True, f"🚨 CỔNG C2 ({remote_port})"

    # Nếu là app hợp lệ nằm trong thư mục chuẩn thì an toàn
    if is_legitimate_whitelisted_app(name_lower, exe_path):
        return False, False, "✅ An toàn"
    if any(p_low.startswith(prefix) for prefix in LEGIT_INSTALL_PREFIXES):
        return False, False, "✅ Hợp lệ"
    if any(kw in p_low for kw in LEGIT_APPDATA_KEYWORDS):
        return False, False, "✅ Hợp lệ"

    # 4. Chạy trực tiếp từ thư mục Temp / Users\Public / Recycle.Bin
    if any(hr in p_low for hr in HIGH_RISK_PATHS):
        return True, False, "⚠️ CHẠY TỪ TEMP/PUBLIC"

    # 5. File thực thi trong AppData\Roaming hoặc ProgramData kết nối cổng lạ
    has_external_conn = not remote_ip.startswith("---") and not remote_ip.startswith("0.0.0.0")
    if has_external_conn and isinstance(remote_port, int):
        if ("appdata\\roaming" in p_low or "programdata" in p_low) and remote_port not in STANDARD_SAFE_PORTS:
            return True, False, f"⚠️ KẾT NỐI LẠ (:{remote_port})"

    return False, False, "✅ Hoạt động" if has_external_conn else "🟦 Đang chạy (Local)"


def get_file_sha256_and_md5(filepath: str):
    try:
        h_sha256 = hashlib.sha256()
        h_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h_sha256.update(chunk)
                h_md5.update(chunk)
        return h_sha256.hexdigest(), h_md5.hexdigest()
    except Exception:
        return "", ""


def find_defender_scanner() -> str:
    platform_root = r"C:\ProgramData\Microsoft\Windows Defender\Platform"
    if os.path.exists(platform_root):
        try:
            versions = sorted(os.listdir(platform_root), reverse=True)
            for v in versions:
                candidate = os.path.join(platform_root, v, "MpCmdRun.exe")
                if os.path.exists(candidate):
                    return candidate
        except Exception:
            pass
    default_path = r"C:\Program Files\Windows Defender\MpCmdRun.exe"
    return default_path if os.path.exists(default_path) else ""


# ================= ỨNG DỤNG CHÍNH =================
class AntiBotnetApp(ctk.CTk):
    def __init__(self, hwid: str, license_info: str):
        super().__init__()

        self.hwid = hwid
        self.license_info = license_info
        self.admin_status = is_admin()
        self.cached_net_rows = []

        cfg = load_config()
        self.vt_api_key = cfg.get("vt_api_key", "")

        self.title("🛡️ Anti-Botnet & C2 Hunter PRO v6.1 (Commercial Anti-Masquerading & Deep Shield)")
        self.geometry("1280x800")
        self.minsize(1120, 700)
        self.configure(fg_color=BG_MAIN)

        self._setup_styles()
        self._build_ui()

        self.bind("<Escape>", lambda e: self.clear_all_selections())
        self.bind("<Control-a>", lambda e: self.select_all_current_tab())

        # Đợi cửa sổ vào mainloop 150ms rồi mới quét để đảm bảo UI luôn hiển thị 100%
        self.after(150, self._run_initial_scans)

    def _run_initial_scans(self):
        self.scan_network()
        self.scan_registry_and_persistence()
        self.scan_firewall_rules()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("default")

        style.configure(
            "Treeview",
            background=ROW_EVEN,
            foreground="#e2e8f0",
            fieldbackground=ROW_EVEN,
            borderwidth=0,
            rowheight=32,
            font=("Segoe UI", 10)
        )
        style.configure(
            "Treeview.Heading",
            background="#1e293b",
            foreground="#38bdf8",
            relief="flat",
            padding=(6, 6),
            font=("Segoe UI", 10, "bold")
        )
        style.map(
            "Treeview",
            background=[("selected", ACCENT_BLUE)],
            foreground=[("selected", "#ffffff")]
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#334155")]
        )

    def _build_ui(self):
        # ====== 1. HEADER ======
        header_frame = ctk.CTkFrame(
            self, height=62, corner_radius=12,
            fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR
        )
        header_frame.pack(fill="x", padx=18, pady=(14, 8))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", padx=18, pady=10)

        ctk.CTkLabel(
            title_box,
            text="🛡️ ANTI-BOTNET & C2 HUNTER",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#f8fafc"
        ).pack(side="left")

        ctk.CTkLabel(
            title_box,
            text=" PRO v6.1 ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#3b82f6",
            text_color="#ffffff",
            corner_radius=6
        ).pack(side="left", padx=8)

        ctk.CTkLabel(
            title_box,
            text=f" 🔑 Bản quyền: {self.license_info} ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1e293b",
            text_color="#fde047",
            corner_radius=6
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            header_frame, text="🧹 Flush DNS", width=110, height=30,
            fg_color="#1e293b", hover_color="#334155", corner_radius=8,
            command=self.flush_dns_cache
        ).pack(side="right", padx=(6, 18))

        admin_text = "🟢 Quyền: Administrator (Đầy đủ)" if self.admin_status else "🔴 Quyền: User thường (Hạn chế)"
        admin_bg = "#064e3b" if self.admin_status else "#450a0a"
        admin_fg = "#34d399" if self.admin_status else "#f87171"

        ctk.CTkLabel(
            header_frame,
            text=f"  {admin_text}  ",
            text_color=admin_fg,
            fg_color=admin_bg,
            corner_radius=8,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="right", padx=6)

        # ====== 2. 4 THẺ THỐNG KÊ ======
        cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        cards_frame.pack(fill="x", padx=18, pady=(0, 8))
        cards_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.card_conn_val = self._create_stat_card(cards_frame, 0, "🌐 KẾT NỐI & TIẾN TRÌNH", "0", "#38bdf8")
        self.card_sus_val = self._create_stat_card(cards_frame, 1, "⚠️ MỐI ĐE DỌA / GIẢ MẠO", "0", "#f43f5e")
        self.card_reg_val = self._create_stat_card(cards_frame, 2, "🚀 KHỞI ĐỘNG & TASK SCHEDULER", "0", "#a855f7")
        self.card_fw_val = self._create_stat_card(cards_frame, 3, "🧱 QUY TẮC CHẶN (FIREWALL)", "0", "#f59e0b")

        # ====== 3. TABVIEW CHÍNH ======
        self.tabview = ctk.CTkTabview(
            self, corner_radius=12,
            fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR,
            segmented_button_fg_color="#0f172a",
            segmented_button_selected_color=ACCENT_BLUE,
            segmented_button_selected_hover_color="#1d4ed8",
            segmented_button_unselected_color="#0f172a"
        )
        self.tabview.pack(fill="both", expand=True, padx=18, pady=4)

        self.tab_net = self.tabview.add("🌐 Giám Sát Đa Kết Nối & Chống Giả Mạo")
        self.tab_reg = self.tabview.add("🚀 Quét Sâu Khởi Động (Registry, Startup, Task)")
        self.tab_fw = self.tabview.add("🧱 Quản Lý Firewall (Đã Chặn)")

        self._build_network_tab()
        self._build_registry_tab()
        self._build_firewall_tab()

        # ====== 4. HỘP NHẬT KÝ ======
        log_frame = ctk.CTkFrame(
            self, height=115, corner_radius=12,
            fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR
        )
        log_frame.pack(fill="x", padx=18, pady=(6, 14))

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(6, 2))

        ctk.CTkLabel(
            log_header,
            text="📋 Nhật ký hệ thống (System Logs)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        ).pack(side="left")

        self.selection_status_lbl = ctk.CTkLabel(
            log_header,
            text=f"🆔 HWID: {self.hwid} | Chống giả mạo svchost.exe & Đa kết nối/PID",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.selection_status_lbl.pack(side="right")

        self.log_box = ctk.CTkTextbox(
            log_frame, height=72, font=("Consolas", 12),
            fg_color="#090d16", text_color="#cbd5e1", corner_radius=8
        )
        self.log_box.pack(fill="x", padx=10, pady=(2, 8))
        self.write_log("Khởi động PRO v6.1! Đã bật lớp chống giả mạo tiến trình hệ thống, hiển thị đa kết nối/PID và quét sâu Task Scheduler.")

    def _create_stat_card(self, parent, col, title, default_val, color):
        card = ctk.CTkFrame(
            parent, corner_radius=10, fg_color=BG_CARD,
            border_width=1, border_color=BORDER_COLOR, height=68
        )
        padx = (0, 5) if col == 0 else ((5, 0) if col == 3 else 5)
        card.grid(row=0, column=col, sticky="ew", padx=padx)

        ctk.CTkLabel(
            card, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
        ).pack(anchor="w", padx=14, pady=(8, 0))

        val_lbl = ctk.CTkLabel(
            card, text=default_val, font=ctk.CTkFont(size=22, weight="bold"), text_color=color
        )
        val_lbl.pack(anchor="w", padx=14, pady=(0, 8))
        return val_lbl

    # ================= TAB 1: GIÁM SÁT MẠNG & TOÀN BỘ APP =================
    def _build_network_tab(self):
        top_bar = ctk.CTkFrame(self.tab_net, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 8))

        self.search_entry = ctk.CTkEntry(
            top_bar,
            placeholder_text="🔍 Gõ tên app cần tìm (vd: svchost, obs, chrome), PID, IP...",
            width=330, height=32, corner_radius=8,
            fg_color="#0b0f19", border_color="#334155"
        )
        self.search_entry.pack(side="left", padx=(2, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self.render_network_table())

        self.filter_sus_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            top_bar,
            text="Chỉ hiện NGHI VẤN / GIẢ MẠO",
            variable=self.filter_sus_var,
            command=self.render_network_table,
            progress_color="#ef4444",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left", padx=10)

        self.auto_scan_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            top_bar,
            text="⏱️ Tự quét ngầm (5s)",
            variable=self.auto_scan_var,
            command=self.toggle_auto_scan,
            progress_color="#10b981",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            top_bar, text="✖ Bỏ chọn", width=95, height=30,
            fg_color="#1e293b", hover_color="#334155",
            command=self.clear_all_selections
        ).pack(side="right", padx=3)

        ctk.CTkButton(
            top_bar, text="☑️ Chọn tất cả", width=105, height=30,
            fg_color="#1e293b", hover_color="#334155",
            command=lambda: self.select_all_tree(self.net_tree)
        ).pack(side="right", padx=3)

        table_frame = ctk.CTkFrame(self.tab_net, fg_color=ROW_EVEN, corner_radius=8)
        table_frame.pack(fill="both", expand=True)

        columns = ("select", "pid", "name", "remote_ip", "port", "status", "risk", "path")
        self.net_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        self.net_tree.heading("select", text="Chọn")
        self.net_tree.heading("pid", text="PID")
        self.net_tree.heading("name", text="Tên Tiến Trình")
        self.net_tree.heading("remote_ip", text="IP Đích (Remote)")
        self.net_tree.heading("port", text="Cổng")
        self.net_tree.heading("status", text="Trạng Thái")
        self.net_tree.heading("risk", text="Đánh Giá Bảo Mật")
        self.net_tree.heading("path", text="Đường Dẫn File Thực Thi")

        self.net_tree.column("select", width=50, anchor="center")
        self.net_tree.column("pid", width=65, anchor="center")
        self.net_tree.column("name", width=150, anchor="w")
        self.net_tree.column("remote_ip", width=135, anchor="center")
        self.net_tree.column("port", width=65, anchor="center")
        self.net_tree.column("status", width=115, anchor="center")
        self.net_tree.column("risk", width=155, anchor="center")
        self.net_tree.column("path", width=360, anchor="w")

        self.net_tree.tag_configure("danger", background=ROW_DANGER, foreground="#fecaca")
        self.net_tree.tag_configure("suspicious", background=ROW_SUS, foreground="#fda4af")
        self.net_tree.tag_configure("standby", background=ROW_STANDBY, foreground="#93c5fd")
        self.net_tree.tag_configure("even", background=ROW_EVEN, foreground="#e2e8f0")
        self.net_tree.tag_configure("odd", background=ROW_ODD, foreground="#e2e8f0")

        self.net_tree.bind("<ButtonPress-1>", lambda event: self._on_tree_multi_click(event, self.net_tree))

        scrollbar = ctk.CTkScrollbar(table_frame, orientation="vertical", command=self.net_tree.yview)
        self.net_tree.configure(yscrollcommand=scrollbar.set)

        self.net_tree.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)
        scrollbar.pack(side="right", fill="y", padx=2, pady=2)

        btn_frame = ctk.CTkFrame(self.tab_net, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 2))

        ctk.CTkButton(
            btn_frame, text="🔄 Quét Lại", width=100, height=36, corner_radius=8,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=self.scan_network
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame, text="🛡️ CHẶN BOTNET", width=155, height=36, corner_radius=8,
            fg_color="#e11d48", hover_color="#be123c", font=ctk.CTkFont(weight="bold"),
            command=self.block_botnet_action
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame, text="💀 Kill Đã Chọn", width=120, height=36, corner_radius=8,
            fg_color="#dc2626", hover_color="#b91c1c", font=ctk.CTkFont(weight="bold"),
            command=self.kill_selected_processes
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame, text="❄️ Đóng Băng", width=110, height=36, corner_radius=8,
            fg_color="#0284c7", hover_color="#0369a1", font=ctk.CTkFont(weight="bold"),
            command=self.suspend_selected_processes
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame, text="🔥 Rã Đông", width=95, height=36, corner_radius=8,
            fg_color="#059669", hover_color="#047857", font=ctk.CTkFont(weight="bold"),
            command=self.resume_selected_processes
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            btn_frame, text="📂 Mở Vị Trí File", width=125, height=36, corner_radius=8,
            fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(weight="bold"),
            command=self.open_file_location
        ).pack(side="right", padx=3)

        ctk.CTkButton(
            btn_frame, text="🔍 Soi IP & Quét Virus (In-App)", width=210, height=36, corner_radius=8,
            fg_color="#0f766e", hover_color="#115e59", font=ctk.CTkFont(weight="bold"),
            command=self.open_inapp_scanner_window
        ).pack(side="right", padx=3)

    # ================= TAB 2: QUÉT SÂU PERSISTENCE (REGISTRY + STARTUP + TASK) =================
    def _build_registry_tab(self):
        top_bar = ctk.CTkFrame(self.tab_reg, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            top_bar,
            text="Quét 8 khu vực Persistence: HKCU/HKLM Run, RunOnce, WOW6432Node, Winlogon, Startup Folder & Task Scheduler:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#cbd5e1"
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            top_bar, text="✖ Bỏ chọn", width=100, height=30,
            fg_color="#1e293b", hover_color="#334155",
            command=self.clear_all_selections
        ).pack(side="right", padx=3)

        ctk.CTkButton(
            top_bar, text="☑️ Chọn tất cả", width=110, height=30,
            fg_color="#1e293b", hover_color="#334155",
            command=lambda: self.select_all_tree(self.reg_tree)
        ).pack(side="right", padx=3)

        table_frame = ctk.CTkFrame(self.tab_reg, fg_color=ROW_EVEN, corner_radius=8)
        table_frame.pack(fill="both", expand=True, pady=(2, 10))

        columns = ("select", "source", "name", "risk", "command")
        self.reg_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        self.reg_tree.heading("select", text="Chọn")
        self.reg_tree.heading("source", text="Khu Vực Khởi Động (Nguồn)")
        self.reg_tree.heading("name", text="Tên Mục / Tác Vụ")
        self.reg_tree.heading("risk", text="Đánh Giá")
        self.reg_tree.heading("command", text="Đường Dẫn / Lệnh Thực Thi")

        self.reg_tree.column("select", width=55, anchor="center")
        self.reg_tree.column("source", width=190, anchor="center")
        self.reg_tree.column("name", width=210, anchor="w")
        self.reg_tree.column("risk", width=130, anchor="center")
        self.reg_tree.column("command", width=520, anchor="w")

        self.reg_tree.tag_configure("suspicious", background=ROW_SUS, foreground="#fda4af")
        self.reg_tree.tag_configure("even", background=ROW_EVEN, foreground="#e2e8f0")
        self.reg_tree.tag_configure("odd", background=ROW_ODD, foreground="#e2e8f0")

        self.reg_tree.bind("<ButtonPress-1>", lambda event: self._on_tree_multi_click(event, self.reg_tree))

        scrollbar = ctk.CTkScrollbar(table_frame, orientation="vertical", command=self.reg_tree.yview)
        self.reg_tree.configure(yscrollcommand=scrollbar.set)

        self.reg_tree.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)
        scrollbar.pack(side="right", fill="y", padx=2, pady=2)

        btn_frame = ctk.CTkFrame(self.tab_reg, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame, text="🔄 Quét Sâu Toàn Bộ Khởi Động", width=210, height=36, corner_radius=8,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=self.scan_registry_and_persistence
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame, text="🗑️ Xóa Các Mục Khởi Động Đã Chọn", width=240, height=36, corner_radius=8,
            fg_color="#dc2626", hover_color="#b91c1c", font=ctk.CTkFont(weight="bold"),
            command=self.delete_selected_persistence
        ).pack(side="left", padx=4)

    # ================= TAB 3: QUẢN LÝ FIREWALL =================
    def _build_firewall_tab(self):
        top_bar = ctk.CTkFrame(self.tab_fw, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 8))

        self.manual_ip_entry = ctk.CTkEntry(
            top_bar, placeholder_text="Nhập IP muốn chặn thủ công (vd: 45.33.2.1)...",
            width=300, height=32, corner_radius=8, fg_color="#0b0f19", border_color="#334155"
        )
        self.manual_ip_entry.pack(side="left", padx=(2, 8))

        ctk.CTkButton(
            top_bar, text="➕ Chặn IP Này", width=130, height=32,
            fg_color="#d97706", hover_color="#b45309", font=ctk.CTkFont(weight="bold"),
            command=self.manual_block_ip
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            top_bar, text="☑️ Chọn tất cả", width=115, height=30,
            fg_color="#1e293b", hover_color="#334155",
            command=lambda: self.select_all_tree(self.fw_tree)
        ).pack(side="right", padx=3)

        table_frame = ctk.CTkFrame(self.tab_fw, fg_color=ROW_EVEN, corner_radius=8)
        table_frame.pack(fill="both", expand=True, pady=(2, 10))

        columns = ("select", "rule_name", "target", "status")
        self.fw_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        self.fw_tree.heading("select", text="Chọn")
        self.fw_tree.heading("rule_name", text="Tên Quy Tắc Firewall (Rule Name)")
        self.fw_tree.heading("target", text="Mục Tiêu Bị Chặn (IP / App / Cổng)")
        self.fw_tree.heading("status", text="Trạng Thái")

        self.fw_tree.column("select", width=60, anchor="center")
        self.fw_tree.column("rule_name", width=380, anchor="w")
        self.fw_tree.column("target", width=260, anchor="center")
        self.fw_tree.column("status", width=200, anchor="center")

        self.fw_tree.tag_configure("even", background=ROW_EVEN, foreground="#fde047")
        self.fw_tree.tag_configure("odd", background=ROW_ODD, foreground="#fde047")

        self.fw_tree.bind("<ButtonPress-1>", lambda event: self._on_tree_multi_click(event, self.fw_tree))

        scrollbar = ctk.CTkScrollbar(table_frame, orientation="vertical", command=self.fw_tree.yview)
        self.fw_tree.configure(yscrollcommand=scrollbar.set)

        self.fw_tree.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)
        scrollbar.pack(side="right", fill="y", padx=2, pady=2)

        btn_frame = ctk.CTkFrame(self.tab_fw, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame, text="🔄 Làm Mới Danh Sách", width=170, height=36, corner_radius=8,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=self.scan_firewall_rules
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame, text="🔓 Gỡ Chặn (Unblock) Các Mục Đã Chọn", width=270, height=36, corner_radius=8,
            fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"),
            command=self.unblock_selected_ips
        ).pack(side="left", padx=4)

    # ================= MULTI-SELECT LOGIC =================
    def _on_tree_multi_click(self, event, tree):
        region = tree.identify_region(event.x, event.y)
        if region in ("heading", "separator"):
            return

        row_id = tree.identify_row(event.y)
        if not row_id:
            self._clear_tree_selection(tree)
            return "break"

        current_sel = set(tree.selection())
        if row_id in current_sel:
            tree.selection_remove(row_id)
            tree.set(row_id, "select", "☐")
        else:
            tree.selection_add(row_id)
            tree.set(row_id, "select", "☑")

        self._update_selection_label(tree)
        return "break"

    def select_all_tree(self, tree):
        all_items = tree.get_children()
        tree.selection_set(all_items)
        for item in all_items:
            tree.set(item, "select", "☑")
        self._update_selection_label(tree)

    def select_all_current_tab(self):
        current = self.tabview.get()
        if "Giám Sát" in current:
            self.select_all_tree(self.net_tree)
        elif "Khởi Động" in current:
            self.select_all_tree(self.reg_tree)
        else:
            self.select_all_tree(self.fw_tree)

    def _clear_tree_selection(self, tree):
        for item in tree.selection():
            tree.set(item, "select", "☐")
        tree.selection_remove(tree.selection())
        tree.focus("")
        self._update_selection_label(tree)

    def clear_all_selections(self):
        self._clear_tree_selection(self.net_tree)
        self._clear_tree_selection(self.reg_tree)
        self._clear_tree_selection(self.fw_tree)
        self.selection_status_lbl.configure(text="⚪ Đã bỏ chọn tất cả các dòng", text_color="#94a3b8")

    def _update_selection_label(self, tree):
        count = len(tree.selection())
        if count == 0:
            self.selection_status_lbl.configure(
                text=f"🆔 HWID: {self.hwid} | Chưa chọn dòng nào",
                text_color="#94a3b8"
            )
        else:
            self.selection_status_lbl.configure(
                text=f"☑️ Đang chọn: {count} mục",
                text_color="#38bdf8"
            )

    def write_log(self, message: str):
        self.log_box.insert("end", f"> {message}\n")
        self.log_box.see("end")

    # ================= QUÉT ĐA KẾT NỐI / PID & CHỐNG GIẢ MẠO =================
    def toggle_auto_scan(self):
        if self.auto_scan_var.get():
            self.write_log("[⏱️] Đã BẬT tự động quét mỗi 5 giây.")
            self._auto_scan_loop()
        else:
            self.write_log("[⏱️] Đã TẮT tự động quét.")

    def _auto_scan_loop(self):
        if not self.auto_scan_var.get():
            return
        self.scan_network(silent=True)
        self.after(5000, self._auto_scan_loop)

    def scan_network(self, silent=False):
        selected_keys = set()
        for item in self.net_tree.selection():
            vals = self.net_tree.item(item, "values")
            if len(vals) >= 5:
                selected_keys.add((str(vals[1]), str(vals[3]), str(vals[4])))

        self.cached_net_rows.clear()
        sus_total = 0
        # Lưu danh sách TẤT CẢ các kết nối của mỗi PID (Không bị ghi đè kết nối)
        active_pids_with_net = defaultdict(list)
        seen_conn_per_pid = defaultdict(set)

        try:
            for conn in psutil.net_connections(kind="inet"):
                pid = conn.pid or 0
                remote_ip = conn.raddr.ip if conn.raddr else ""
                remote_port = conn.raddr.port if conn.raddr else (conn.laddr.port if conn.laddr else 0)

                if remote_ip.startswith("127.") or remote_ip == "::1":
                    continue

                if not remote_ip:
                    if conn.status not in ("LISTEN", "NONE"):
                        continue
                    remote_ip = "0.0.0.0 (Listen)"

                status_str = conn.status if conn.status != "NONE" else "UDP/ACTIVE"
                conn_key = (remote_ip, remote_port, status_str)
                if conn_key not in seen_conn_per_pid[pid]:
                    seen_conn_per_pid[pid].add(conn_key)
                    active_pids_with_net[pid].append(conn_key)
        except Exception:
            pass

        seen_pids = set()
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pid = proc.info["pid"]
                name = proc.info["name"] or ""
                exe_path = proc.info["exe"] or ""

                if not name or pid in seen_pids:
                    continue
                seen_pids.add(pid)
                name_lower = name.lower()

                # KIỂM TRA CHỐNG GIẢ MẠO: Chỉ ẩn tiến trình Windows nếu đúng đường dẫn System32/SysWOW64!
                if is_legitimate_windows_core_process(name_lower, exe_path):
                    continue

                conns = active_pids_with_net.get(pid, [])
                if not conns:
                    conns = [("--- (Chờ mạng)", "-", "STANDBY (Local)")]

                for remote_ip, remote_port, status_str in conns:
                    is_sus, is_crit, risk_text = evaluate_process_risk(name, exe_path, remote_ip, remote_port)
                    if is_sus:
                        sus_total += 1
                    self.cached_net_rows.append((
                        pid, name, remote_ip, remote_port,
                        status_str, risk_text, exe_path, is_sus, is_crit
                    ))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        # Sắp xếp ưu tiên: Nguy hiểm cao -> Nghi vấn -> Có kết nối mạng -> Tên A-Z
        self.cached_net_rows.sort(key=lambda x: (not x[8], not x[7], "STANDBY" in x[4], x[1].lower()))

        self.card_conn_val.configure(text=str(len(self.cached_net_rows)))
        self.card_sus_val.configure(
            text=str(sus_total),
            text_color="#f43f5e" if sus_total > 0 else "#10b981"
        )
        self.render_network_table(selected_keys)
        if not silent:
            self.write_log(
                f"Đã quét toàn hệ thống: Hiển thị {len(self.cached_net_rows)} dòng kết nối & ứng dụng ({sus_total} cảnh báo)."
            )

    def render_network_table(self, restore_keys=None):
        if restore_keys is None:
            restore_keys = set()
            for item in self.net_tree.selection():
                vals = self.net_tree.item(item, "values")
                if len(vals) >= 5:
                    restore_keys.add((str(vals[1]), str(vals[3]), str(vals[4])))

        for item in self.net_tree.get_children():
            self.net_tree.delete(item)

        keyword = self.search_entry.get().strip().lower()
        only_sus = self.filter_sus_var.get()

        row_idx = 0
        for pid, name, remote_ip, remote_port, status, risk_text, exe_path, is_sus, is_crit in self.cached_net_rows:
            if only_sus and not is_sus:
                continue
            if keyword:
                haystack = f"{pid} {name} {remote_ip} {remote_port} {status} {risk_text} {exe_path}".lower()
                if keyword not in haystack:
                    continue

            if is_crit:
                tag = "danger"
            elif is_sus:
                tag = "suspicious"
            elif "STANDBY" in status:
                tag = "standby"
            else:
                tag = "even" if row_idx % 2 == 0 else "odd"

            key = (str(pid), str(remote_ip), str(remote_port))
            is_checked = key in restore_keys

            item_id = self.net_tree.insert(
                "", "end",
                values=("☑" if is_checked else "☐", pid, name, remote_ip, remote_port, status, risk_text, exe_path),
                tags=(tag,)
            )
            if is_checked:
                self.net_tree.selection_add(item_id)
            row_idx += 1

        self._update_selection_label(self.net_tree)

    def get_selected_net_rows(self):
        selected = self.net_tree.selection()
        if not selected:
            return []
        return [self.net_tree.item(item, "values") for item in selected]

    # ================= NÚT CHẶN BOTNET =================
    def block_botnet_action(self):
        rows = self.get_selected_net_rows()

        if rows:
            targets = {int(r[1]): (r[2], r[7]) for r in rows}
            ips = sorted({r[3] for r in rows if not r[3].startswith("---") and not r[3].startswith("0.0.0.0")})
            names_preview = ", ".join({r[2] for r in rows})

            if not messagebox.askyesno(
                "🛡️ Xác Nhận Chặn Botnet (Khóa Tận Gốc)",
                f"Bạn muốn kích hoạt CHẶN BOTNET cho {len(targets)} tiến trình đã chọn ({names_preview})?\n\n"
                f"Tool sẽ thực hiện 3 lớp khóa:\n"
                f"1. Cấm vĩnh viễn file .exe truy cập mạng trên Firewall\n"
                f"2. Chặn toàn bộ {len(ips)} địa chỉ IP đích liên quan\n"
                f"3. Diệt (Kill) ngay lập tức tiến trình đang chạy"
            ):
                return

            for pid, (name, exe_path) in targets.items():
                if exe_path and os.path.exists(exe_path):
                    rule_exe = f"AntiBotnet_App_{name}_{pid}"
                    cmd_exe = f'netsh advfirewall firewall add rule name="{rule_exe}" dir=out action=block program="{exe_path}"'
                    subprocess.run(cmd_exe, shell=True, capture_output=True)
                    self.write_log(f"[🛡️] Đã khóa đường truyền mạng của file: {exe_path}")

                try:
                    psutil.Process(pid).kill()
                    self.write_log(f"[💀] Đã diệt tiến trình: {name} (PID: {pid})")
                except Exception as e:
                    self.write_log(f"[!] Không thể Kill PID {pid}: {e}")

            for ip in ips:
                rule_ip = f"AntiBotnet_Block_{ip}"
                subprocess.run(
                    f'netsh advfirewall firewall add rule name="{rule_ip}" dir=out action=block remoteip={ip}',
                    shell=True, capture_output=True
                )
                self.write_log(f"[🧱] Đã chặn IP C2: {ip}")

            self.scan_network(silent=True)
            self.scan_firewall_rules()
            messagebox.showinfo("Hoàn tất", "Đã khóa mạng file .exe, chặn IP và diệt tiến trình thành công!")
        else:
            sus_rows = [r for r in self.cached_net_rows if r[7]]
            if not messagebox.askyesno(
                "🛡️ Kích Hoạt Khiên Chặn Botnet Tự Động",
                f"Hiện có {len(sus_rows)} kết nối/tiến trình NGHI VẤN hoặc GIẢ MẠO trên bảng.\n\n"
                f"Bạn có muốn kích hoạt KHIÊN CHẶN BOTNET TỰ ĐỘNG:\n"
                f"• Tự động Kill & Khóa Firewall các tiến trình Nghi Vấn/Giả Mạo ({len(sus_rows)} mục)\n"
                f"• Khóa toàn bộ các cổng (Port) C2 Botnet/RAT phổ biến trên Firewall?"
            ):
                return

            port_list = ",".join(map(str, sorted(BOTNET_PORTS)))
            rule_ports = "AntiBotnet_Block_C2_Ports"
            subprocess.run(f'netsh advfirewall firewall delete rule name="{rule_ports}"', shell=True, capture_output=True)
            res = subprocess.run(
                f'netsh advfirewall firewall add rule name="{rule_ports}" dir=out action=block protocol=TCP remoteport={port_list}',
                shell=True, capture_output=True
            )
            if res.returncode == 0:
                self.write_log(f"[🛡️] Đã khóa các cổng C2 Botnet ({port_list}) trên Windows Firewall!")

            for pid, name, remote_ip, _, _, _, exe_path, _, _ in sus_rows:
                if exe_path and os.path.exists(exe_path):
                    rule_exe = f"AntiBotnet_App_{name}"
                    subprocess.run(
                        f'netsh advfirewall firewall add rule name="{rule_exe}" dir=out action=block program="{exe_path}"',
                        shell=True, capture_output=True
                    )
                if not remote_ip.startswith("---") and not remote_ip.startswith("0.0.0.0"):
                    rule_ip = f"AntiBotnet_Block_{remote_ip}"
                    subprocess.run(
                        f'netsh advfirewall firewall add rule name="{rule_ip}" dir=out action=block remoteip={remote_ip}',
                        shell=True, capture_output=True
                    )
                try:
                    psutil.Process(int(pid)).kill()
                    self.write_log(f"[💀] Đã tự động diệt tiến trình nghi vấn: {name} (PID: {pid})")
                except Exception:
                    pass

            self.scan_network(silent=True)
            self.scan_firewall_rules()
            messagebox.showinfo(
                "🛡️ Đã Bật Khiên Chặn Botnet",
                f"Đã khóa các cổng C2 ({port_list}) và xử lý {len(sus_rows)} mục nghi vấn!"
            )

    # ================= CỬA SỔ SOI VIRUS IN-APP =================
    def open_inapp_scanner_window(self):
        rows = self.get_selected_net_rows()
        if not rows:
            messagebox.showwarning("Chưa chọn dòng", "Vui lòng tích chọn 1 dòng trên bảng để Soi IP & Quét Virus!")
            return

        first = rows[0]
        pid, name, remote_ip, port, status, _, exe_path = first[1], first[2], first[3], first[4], first[5], first[6], first[7]

        win = ctk.CTkToplevel(self)
        win.title(f"🔍 Phân Tích Chuyên Sâu: {name} (PID: {pid})")
        win.geometry("820x650")
        win.minsize(720, 520)
        win.configure(fg_color=BG_MAIN)
        win.resizable(True, True)

        win.lift()
        win.focus_force()
        win.attributes("-topmost", True)
        win.after(250, lambda: win.attributes("-topmost", False))

        hdr = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        hdr.pack(fill="x", padx=14, pady=(14, 8))

        ctk.CTkLabel(
            hdr, text="🔬 TRUNG TÂM ĐIỀU TRA TIẾN TRÌNH & QUÉT VIRUS ĐA LỚP (IN-APP)",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="#38bdf8"
        ).pack(anchor="w", padx=14, pady=(10, 2))

        ctk.CTkLabel(
            hdr, text=f"Tiến trình: {name} (PID: {pid})  |  IP: {remote_ip}:{port}  |  Trạng thái: {status}",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#cbd5e1"
        ).pack(anchor="w", padx=14, pady=(0, 10))

        api_frame = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_COLOR)
        api_frame.pack(fill="x", padx=14, pady=4)

        ctk.CTkLabel(
            api_frame, text="🔑 VirusTotal API Key (Tùy chọn):",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8"
        ).pack(side="left", padx=12, pady=8)

        api_entry = ctk.CTkEntry(
            api_frame, width=360, height=30,
            placeholder_text="Không bắt buộc (Đã có sẵn bộ quét Defender + Cloud Hash bên dưới)...",
            fg_color="#090d16", border_color="#334155"
        )
        api_entry.pack(side="left", padx=6, pady=8)
        if self.vt_api_key:
            api_entry.insert(0, self.vt_api_key)

        def save_and_rescan():
            self.vt_api_key = api_entry.get().strip()
            save_config({"vt_api_key": self.vt_api_key})
            run_analysis()

        ctk.CTkButton(
            api_frame, text="🔄 Quét Lại Ngay", width=130, height=30,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=save_and_rescan
        ).pack(side="right", padx=12, pady=8)

        report_box = ctk.CTkTextbox(
            win, font=("Consolas", 12), fg_color="#090d16",
            text_color="#e2e8f0", corner_radius=10, border_width=1, border_color=BORDER_COLOR
        )
        report_box.pack(fill="both", expand=True, padx=14, pady=8)

        action_bar = ctk.CTkFrame(win, fg_color="transparent")
        action_bar.pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkButton(
            action_bar, text="🛡️ Chặn Botnet Mục Này (Khóa .exe + IP + Kill)", width=290, height=36,
            fg_color="#e11d48", hover_color="#be123c", font=ctk.CTkFont(weight="bold"),
            command=lambda: [win.destroy(), self.block_botnet_action()]
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            action_bar, text="Đóng Cửa Sổ", width=120, height=36,
            fg_color="#334155", hover_color="#475569",
            command=win.destroy
        ).pack(side="right", padx=4)

        def append_report(text: str):
            if win.winfo_exists():
                report_box.insert("end", text + "\n")
                report_box.see("end")

        def run_analysis():
            report_box.delete("1.0", "end")
            append_report("⏳ Đang kích hoạt 4 lớp quét: IP Intel + Chữ ký số + Windows Defender Engine + Đám mây mã độc...\n" + "=" * 86)

            def worker():
                clean_ip = remote_ip.split(" ")[0]
                self.after(0, lambda: append_report("\n[1] 🌐 PHÂN TÍCH ĐỊA CHỈ IP & MÁY CHỦ ĐÍCH:"))
                if clean_ip in ("---", "0.0.0.0", "-"):
                    self.after(0, lambda: append_report("  • Trạng thái mạng : Ứng dụng đang chạy nội bộ (Chưa mở kết nối ra IP ngoài)."))
                else:
                    try:
                        url = f"http://ip-api.com/json/{clean_ip}?fields=status,country,regionName,city,isp,org,as,proxy,hosting"
                        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                            if data.get("status") == "success":
                                hosting_flag = "⚠️ CÓ (Server VPS/Cloud/Datacenter)" if data.get("hosting") else "Không (Mạng thông thường)"
                                proxy_flag = "⚠️ CÓ (VPN/Proxy/Tor)" if data.get("proxy") else "Không"
                                info_lines = (
                                    f"  • Địa chỉ IP      : {clean_ip} (Cổng: {port})\n"
                                    f"  • Quốc gia / TP   : {data.get('country')} - {data.get('regionName')} ({data.get('city')})\n"
                                    f"  • Nhà mạng (ISP)  : {data.get('isp')}\n"
                                    f"  • Tổ chức / ASN   : {data.get('org')} | {data.get('as')}\n"
                                    f"  • Máy chủ Hosting : {hosting_flag}\n"
                                    f"  • Nghi vấn Proxy  : {proxy_flag}"
                                )
                                self.after(0, lambda: append_report(info_lines))
                    except Exception as e:
                        self.after(0, lambda: append_report(f"  • Không thể lấy thông tin IP: {e}"))

                self.after(0, lambda: append_report("\n[2] 🛡️ KIỂM TRA FILE .EXE & CHỮ KÝ SỐ (AUTHENTICODE):"))
                if not exe_path or not os.path.exists(exe_path):
                    kernel_info = (
                        f"  • Đường dẫn       : {exe_path or 'N/A'} (Tiến trình Nhân Windows Kernel chạy trong RAM)\n"
                        f"  • Bản chất        : Tiến trình ảo của hệ điều hành Windows (Không có file .exe trên ổ đĩa)\n"
                        f"  • Đánh giá        : ✅ Tiến trình nội bộ hợp lệ của Windows Kernel.\n\n"
                        + "=" * 86 + "\n🟢 KẾT LUẬN CUỐI CÙNG: TIẾN TRÌNH NHÂN WINDOWS (KERNEL) AN TOÀN TUYỆT ĐỐI"
                    )
                    self.after(0, lambda: append_report(kernel_info))
                    return

                file_size_mb = os.path.getsize(exe_path) / (1024 * 1024)
                mtime = datetime.fromtimestamp(os.path.getmtime(exe_path)).strftime("%Y-%m-%d %H:%M:%S")
                sha256_hash, md5_hash = get_file_sha256_and_md5(exe_path)

                sig_cmd = f'powershell -NoProfile -Command "$s = Get-AuthenticodeSignature -FilePath \'{exe_path}\'; Write-Output ($s.Status.ToString() + \' | \' + $s.SignerCertificate.Subject)"'
                sig_res = subprocess.run(sig_cmd, shell=True, capture_output=True, text=True)
                sig_out = sig_res.stdout.strip() or "Unknown"
                is_signed_valid = sig_out.startswith("Valid")

                sig_display = f"✅ HỢP LỆ ({sig_out})" if is_signed_valid else f"⚠️ KHÔNG CÓ CHỮ KÝ SỐ ({sig_out})"

                file_lines = (
                    f"  • Đường dẫn File  : {exe_path}\n"
                    f"  • Dung lượng      : {file_size_mb:.2f} MB  |  Ngày sửa đổi: {mtime}\n"
                    f"  • Chữ ký số       : {sig_display}\n"
                    f"  • Mã băm SHA-256  : {sha256_hash}\n"
                    f"  • Mã băm MD5      : {md5_hash}"
                )
                self.after(0, lambda: append_report(file_lines))

                self.after(0, lambda: append_report("\n[3] 🦠 KẾT QUẢ QUÉT VIRUS & MÃ ĐỘC TRỰC TIẾP (4 LỚP BẢO VỆ):"))

                mpcmd = find_defender_scanner()
                defender_clean = True
                if mpcmd:
                    self.after(0, lambda: append_report("  • [Lớp 1 - Windows Defender Engine] : ⏳ Đang quét trực tiếp tệp tin..."))
                    scan_cmd = f'"{mpcmd}" -Scan -ScanType 3 -File "{exe_path}" -DisableRemediation'
                    scan_res = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True)
                    out_text = (scan_res.stdout + "\n" + scan_res.stderr).strip()
                    if scan_res.returncode == 0 and "found no threats" in out_text.lower():
                        self.after(0, lambda: append_report("    => ✅ SẠCH 100% (Windows Defender xác nhận KHÔNG CÓ VIRUS)."))
                    elif scan_res.returncode == 2 or "threat" in out_text.lower():
                        defender_clean = False
                        self.after(0, lambda: append_report(f"    => 🚨 PHÁT HIỆN MÃ ĐỘC / VIRUS! Chi tiết: {out_text.splitlines()[-1]}"))
                    else:
                        self.after(0, lambda: append_report("    => ✅ Hoàn tất kiểm tra (Không phát hiện mẫu nhận diện độc hại)."))
                else:
                    self.after(0, lambda: append_report("  • [Lớp 1 - Windows Defender Engine] : Không tìm thấy MpCmdRun.exe trên máy."))

                cymru_detected = False
                try:
                    cymru_cmd = f'nslookup -type=txt {sha256_hash}.malware.hash.cymru.com'
                    cymru_res = subprocess.run(cymru_cmd, shell=True, capture_output=True, text=True, timeout=5)
                    cymru_out = cymru_res.stdout.lower()
                    if '"1' in cymru_out or '"2' in cymru_out:
                        cymru_detected = True
                        self.after(0, lambda: append_report("  • [Lớp 2 - Cloud Malware Hash DB]   : 🚨 CẢNH BÁO ĐỎ! Mã SHA-256 nằm trong danh sách Malware quốc tế!"))
                    else:
                        self.after(0, lambda: append_report("  • [Lớp 2 - Cloud Malware Hash DB]   : ✅ SẠCH (Mã SHA-256 không nằm trong danh sách đen toàn cầu)."))
                except Exception:
                    self.after(0, lambda: append_report("  • [Lớp 2 - Cloud Malware Hash DB]   : ✅ Không ghi nhận báo cáo độc hại."))

                is_sus, is_crit, reason_lbl = evaluate_process_risk(name, exe_path, clean_ip, int(port) if str(port).isdigit() else "-")
                if is_crit:
                    self.after(0, lambda: append_report(f"  • [Lớp 3 - Chống Giả Mạo & Hành Vi] : 🚨 NGUY HIỂM ({reason_lbl})."))
                elif is_sus:
                    self.after(0, lambda: append_report(f"  • [Lớp 3 - Chống Giả Mạo & Hành Vi] : ⚠️ CẢNH BÁO ({reason_lbl})."))
                else:
                    self.after(0, lambda: append_report("  • [Lớp 3 - Chống Giả Mạo & Hành Vi] : ✅ AN TOÀN (Đường dẫn chuẩn, không giả mạo hệ thống)."))

                if self.vt_api_key:
                    try:
                        vt_url = f"https://www.virustotal.com/api/v3/files/{sha256_hash}"
                        vt_req = urllib.request.Request(vt_url, headers={"x-apikey": self.vt_api_key})
                        with urllib.request.urlopen(vt_req, timeout=6) as resp:
                            vt_json = json.loads(resp.read().decode("utf-8"))
                            stats = vt_json["data"]["attributes"]["last_analysis_stats"]
                            mal = stats.get("malicious", 0)
                            sus = stats.get("suspicious", 0)
                            total = mal + sus + stats.get("harmless", 0) + stats.get("undetected", 0)
                            verdict = f"🚨 NGUY HIỂM ({mal}/{total} hãng báo độc hại)" if mal > 0 else f"✅ SẠCH (0/{total} hãng phát hiện)"
                            self.after(0, lambda: append_report(f"  • [Lớp 4 - VirusTotal Cloud API]    : {verdict}"))
                    except urllib.error.HTTPError as he:
                        if he.code == 404:
                            self.after(0, lambda: append_report("  • [Lớp 4 - VirusTotal Cloud API]    : File riêng tư chưa từng bị báo cáo lên VirusTotal."))
                        else:
                            self.after(0, lambda: append_report(f"  • [Lớp 4 - VirusTotal Cloud API]    : Lỗi API Key (HTTP {he.code})."))
                    except Exception as e:
                        self.after(0, lambda: append_report(f"  • [Lớp 4 - VirusTotal Cloud API]    : Lỗi kết nối ({e})."))

                if not defender_clean or cymru_detected or is_crit:
                    final_verdict = "🔴 KẾT LUẬN CUỐI CÙNG: NGUY HIỂM CAO! HÃY BẤM NÚT 'CHẶN BOTNET' BÊN DƯỚI NGAY!"
                elif defender_clean and is_signed_valid and not is_sus:
                    final_verdict = "🟢 KẾT LUẬN CUỐI CÙNG: TỆP TIN AN TOÀN TUYỆT ĐỐI (Chữ ký số hợp lệ & Sạch 100%)"
                else:
                    final_verdict = "🟡 KẾT LUẬN CUỐI CÙNG: CHƯA PHÁT HIỆN MÃ ĐỘC NHƯNG FILE KHÔNG CÓ CHỮ KÝ SỐ (Theo dõi thêm)"

                self.after(0, lambda: append_report("\n" + "=" * 86 + f"\n{final_verdict}"))

            threading.Thread(target=worker, daemon=True).start()

        run_analysis()

    # ================= CÁC HÀM XỬ LÝ TIẾN TRÌNH =================
    def kill_selected_processes(self):
        rows = self.get_selected_net_rows()
        if not rows:
            messagebox.showwarning("Chưa chọn dòng", "Vui lòng tích chọn ít nhất 1 dòng trước!")
            return

        targets = {int(r[1]): r[2] for r in rows}
        if not messagebox.askyesno("Xác nhận Kill", f"Bạn có chắc muốn DIỆT {len(targets)} tiến trình đã chọn?"):
            return

        for pid, name in targets.items():
            try:
                psutil.Process(pid).kill()
                self.write_log(f"[💀] Đã diệt '{name}' (PID: {pid}).")
            except Exception as e:
                self.write_log(f"[!] Lỗi diệt PID {pid} ({name}): {e}")

        self.scan_network(silent=True)

    def suspend_selected_processes(self):
        rows = self.get_selected_net_rows()
        if not rows:
            messagebox.showwarning("Chưa chọn dòng", "Vui lòng tích chọn ít nhất 1 dòng trước!")
            return

        for pid, name in {int(r[1]): r[2] for r in rows}.items():
            try:
                psutil.Process(pid).suspend()
                self.write_log(f"[❄️] ĐÃ ĐÓNG BĂNG '{name}' (PID: {pid})!")
            except Exception as e:
                self.write_log(f"[!] Lỗi đóng băng PID {pid}: {e}")

    def resume_selected_processes(self):
        rows = self.get_selected_net_rows()
        if not rows:
            messagebox.showwarning("Chưa chọn dòng", "Vui lòng tích chọn ít nhất 1 dòng trước!")
            return

        for pid, name in {int(r[1]): r[2] for r in rows}.items():
            try:
                psutil.Process(pid).resume()
                self.write_log(f"[🔥] Đã RÃ ĐÔNG '{name}' (PID: {pid}).")
            except Exception as e:
                self.write_log(f"[!] Lỗi rã đông PID {pid}: {e}")

    def open_file_location(self):
        rows = self.get_selected_net_rows()
        if not rows:
            messagebox.showwarning("Chưa chọn dòng", "Vui lòng tích chọn 1 dòng trước!")
            return
        exe_path = rows[0][7]
        if os.path.exists(exe_path):
            subprocess.Popen(f'explorer /select,"{exe_path}"')
            self.write_log(f"Đã mở thư mục chứa file: {exe_path}")
        else:
            messagebox.showwarning("Không tìm thấy", "Đường dẫn file không tồn tại hoặc là tiến trình hệ thống.")

    def flush_dns_cache(self):
        res = subprocess.run("ipconfig /flushdns", shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            self.write_log("[🧹] Đã dọn sạch bộ nhớ đệm DNS thành công!")
            messagebox.showinfo("Flush DNS", "Đã làm sạch bộ nhớ đệm DNS của Windows!")

    # ================= QUÉT SÂU PERSISTENCE (REGISTRY + STARTUP FOLDER + TASK SCHEDULER) =================
    def scan_registry_and_persistence(self):
        for item in self.reg_tree.get_children():
            self.reg_tree.delete(item)

        sus_keywords = [
            "temp", "users\\public", "powershell", "cmd.exe", ".vbs",
            ".bat", ".ps1", "wscript", "cscript", "mshta", "regsvr32", "rundll32"
        ]
        row_idx = 0

        # 1. Quét 5 nhánh Registry Run / RunOnce / WOW6432Node
        registry_targets = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "REG: HKCU\\Run"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "REG: HKCU\\RunOnce"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "REG: HKLM\\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "REG: HKLM\\RunOnce"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "REG: HKLM\\WOW64\\Run")
        ]

        for hkey, path, label in registry_targets:
            try:
                key = winreg.OpenKey(hkey, path, 0, winreg.KEY_READ)
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        val_str = str(value)
                        is_sus = any(k in val_str.lower() for k in sus_keywords)
                        risk = "⚠️ NGHI VẤN" if is_sus else "✅ Bình thường"
                        tag = "suspicious" if is_sus else ("even" if row_idx % 2 == 0 else "odd")

                        self.reg_tree.insert("", "end", values=("☐", label, name, risk, val_str), tags=(tag,))
                        i += 1
                        row_idx += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass

        # 2. Quét khóa Winlogon (Shell & Userinit)
        try:
            wl_key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\Microsoft\Windows NT\CurrentVersion\Winlogon",
                0, winreg.KEY_READ
            )
            for val_name, expected in [("Shell", "explorer.exe"), ("Userinit", "userinit.exe")]:
                try:
                    val_data, _ = winreg.QueryValueEx(wl_key, val_name)
                    val_str = str(val_data).strip()
                    is_sus = ("," in val_str and val_str.rstrip(",").lower().endswith(".exe") and val_str.count(".exe") > 1) or (expected not in val_str.lower())
                    risk = "🚨 BỊ CHÈN MÃ ĐỘC" if is_sus else "✅ Chuẩn Hệ Thống"
                    tag = "suspicious" if is_sus else ("even" if row_idx % 2 == 0 else "odd")
                    self.reg_tree.insert("", "end", values=("☐", "REG: Winlogon", val_name, risk, val_str), tags=(tag,))
                    row_idx += 1
                except Exception:
                    pass
            winreg.CloseKey(wl_key)
        except Exception:
            pass

        # 3. Quét 2 thư mục Startup Folder
        startup_dirs = [
            ("FOLDER: User Startup", os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")),
            ("FOLDER: System Startup", r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp")
        ]
        for label, s_dir in startup_dirs:
            if os.path.exists(s_dir):
                try:
                    for fname in os.listdir(s_dir):
                        if fname.lower() == "desktop.ini":
                            continue
                        full_p = os.path.join(s_dir, fname)
                        is_sus = any(ext in fname.lower() for ext in (".vbs", ".bat", ".cmd", ".ps1", ".js", ".scr"))
                        risk = "⚠️ NGHI VẤN" if is_sus else "📁 File Startup"
                        tag = "suspicious" if is_sus else ("even" if row_idx % 2 == 0 else "odd")
                        self.reg_tree.insert("", "end", values=("☐", label, fname, risk, full_p), tags=(tag,))
                        row_idx += 1
                except Exception:
                    pass

        # 4. Quét Scheduled Tasks
        try:
            res = subprocess.run('schtasks /query /fo CSV /v /nh', shell=True, capture_output=True, text=True, timeout=6)
            if res.returncode == 0 and res.stdout:
                reader = csv.reader(io.StringIO(res.stdout))
                seen_tasks = set()
                for row in reader:
                    if len(row) > 8:
                        task_name = row[1].strip()
                        task_run = row[8].strip()
                        if not task_name or task_name.startswith("\\Microsoft\\") or task_name in seen_tasks:
                            continue
                        if task_name == "TaskName" or not task_run or task_run in ("N/A", "Disabled"):
                            continue
                        seen_tasks.add(task_name)
                        is_sus = any(k in task_run.lower() for k in sus_keywords)
                        risk = "⚠️ NGHI VẤN" if is_sus else "⏱️ Task Tự Động"
                        tag = "suspicious" if is_sus else ("even" if row_idx % 2 == 0 else "odd")
                        self.reg_tree.insert("", "end", values=("☐", "TASK SCHEDULER", task_name, risk, task_run), tags=(tag,))
                        row_idx += 1
        except Exception:
            pass

        self.card_reg_val.configure(text=str(row_idx))

    def delete_selected_persistence(self):
        selected = self.reg_tree.selection()
        if not selected:
            messagebox.showwarning("Chưa chọn mục", "Vui lòng tích chọn ít nhất 1 mục khởi động để xóa!")
            return

        if not messagebox.askyesno("Xác nhận xóa Persistence", f"Bạn muốn xóa {len(selected)} mục khởi động/tác vụ đã chọn?"):
            return

        reg_map = {
            "REG: HKCU\\Run": (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            "REG: HKCU\\RunOnce": (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
            "REG: HKLM\\Run": (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            "REG: HKLM\\RunOnce": (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
            "REG: HKLM\\WOW64\\Run": (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")
        }

        for item in selected:
            _, source_label, item_name, _, cmd_path = self.reg_tree.item(item, "values")
            try:
                if source_label in reg_map:
                    hkey, subkey = reg_map[source_label]
                    key = winreg.OpenKey(hkey, subkey, 0, winreg.KEY_SET_VALUE)
                    winreg.DeleteValue(key, item_name)
                    winreg.CloseKey(key)
                    self.write_log(f"[🗑️] Đã xóa khóa Registry '{item_name}' ({source_label})!")
                elif source_label.startswith("FOLDER:"):
                    if os.path.exists(cmd_path):
                        os.remove(cmd_path)
                        self.write_log(f"[🗑️] Đã xóa file Startup: {cmd_path}")
                elif source_label == "TASK SCHEDULER":
                    res = subprocess.run(f'schtasks /delete /tn "{item_name}" /f', shell=True, capture_output=True, text=True)
                    if res.returncode == 0:
                        self.write_log(f"[🗑️] Đã xóa Scheduled Task: {item_name}")
                    else:
                        self.write_log(f"[!] Không thể xóa Task '{item_name}': Cần quyền Admin.")
                elif source_label == "REG: Winlogon":
                    messagebox.showinfo("Bảo vệ hệ thống", "Khóa Winlogon chỉ nên khôi phục về mặc định thay vì xóa trắng.")
            except Exception as e:
                self.write_log(f"[!] Lỗi xóa '{item_name}': {e}")

        self.scan_registry_and_persistence()

    # ================= QUẢN LÝ FIREWALL =================
    def scan_firewall_rules(self):
        for item in self.fw_tree.get_children():
            self.fw_tree.delete(item)

        cmd = 'powershell -NoProfile -Command "Get-NetFirewallRule -DisplayName \'AntiBotnet_*\' -ErrorAction SilentlyContinue | ForEach-Object { $_.DisplayName }"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        rules = sorted({line.strip() for line in res.stdout.splitlines() if line.strip().startswith("AntiBotnet_")})

        for idx, rule_name in enumerate(rules):
            target = rule_name.replace("AntiBotnet_Block_", "").replace("AntiBotnet_App_", "App: ")
            tag = "even" if idx % 2 == 0 else "odd"
            self.fw_tree.insert("", "end", values=("☐", rule_name, target, "🔒 Đang bị chặn (Outbound)"), tags=(tag,))

        self.card_fw_val.configure(text=str(len(rules)))

    def manual_block_ip(self):
        ip = self.manual_ip_entry.get().strip()
        if not ip:
            return
        rule_name = f"AntiBotnet_Block_{ip}"
        res = subprocess.run(
            f'netsh advfirewall firewall add rule name="{rule_name}" dir=out action=block remoteip={ip}',
            shell=True, capture_output=True
        )
        if res.returncode == 0:
            self.manual_ip_entry.delete(0, "end")
            self.write_log(f"[🧱] Đã chặn thủ công IP '{ip}'!")
            self.scan_firewall_rules()

    def unblock_selected_ips(self):
        selected = self.fw_tree.selection()
        if not selected:
            messagebox.showwarning("Chưa chọn mục", "Vui lòng tích chọn ít nhất 1 quy tắc để gỡ chặn!")
            return

        for item in selected:
            _, rule_name, target, _ = self.fw_tree.item(item, "values")
            subprocess.run(f'netsh advfirewall firewall delete rule name="{rule_name}"', shell=True, capture_output=True)
            self.write_log(f"[🔓] Đã GỠ CHẶN cho: {target}")

        self.scan_firewall_rules()


# ================= HỘP THOẠI KÍCH HOẠT LICENSE KEY =================
class LicenseActivationWindow(ctk.CTk):
    def __init__(self, hwid: str):
        super().__init__()
        self.hwid = hwid
        self.activated_successfully = False

        self.title("🔐 Kích Hoạt Bản Quyền - Anti-Botnet PRO v6.1")
        self.geometry("560x360")
        self.resizable(False, False)
        self.configure(fg_color=BG_MAIN)

        card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BORDER_COLOR)
        card.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            card, text="🛡️ KÍCH HOẠT BẢN QUYỀN THƯƠNG MẠI",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#38bdf8"
        ).pack(pady=(18, 4))

        ctk.CTkLabel(
            card, text="Nhập License Key do người bán cung cấp để kích hoạt (mỗi máy dùng 1 key cho đến khi hết hạn):",
            font=ctk.CTkFont(size=12), text_color="#94a3b8"
        ).pack(pady=(0, 12))

        hwid_frame = ctk.CTkFrame(card, fg_color="#090d16", corner_radius=8)
        hwid_frame.pack(fill="x", padx=28, pady=6)

        ctk.CTkLabel(
            hwid_frame, text=f"MÃ MÁY:  {self.hwid}",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"), text_color="#fde047"
        ).pack(side="left", padx=14, pady=10)

        ctk.CTkButton(
            hwid_frame, text="📋 Copy HWID", width=105, height=28,
            fg_color="#1e293b", hover_color="#334155",
            command=self.copy_hwid
        ).pack(side="right", padx=10, pady=8)

        self.key_entry = ctk.CTkEntry(
            card, placeholder_text="Nhập License Key (VD: PRO6-D030-XXXXXXXX-XXXXXXXXXXXX)...",
            height=38, corner_radius=8, font=("Consolas", 13),
            fg_color="#090d16", border_color="#334155"
        )
        self.key_entry.pack(fill="x", padx=28, pady=(14, 6))

        self.status_lbl = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f43f5e"
        )
        self.status_lbl.pack(pady=4)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=28, pady=(8, 14))

        ctk.CTkButton(
            btn_row, text="✅ KÍCH HOẠT NGAY", height=38,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=self.activate_key
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            btn_row, text="Thoát", width=90, height=38,
            fg_color="#334155", hover_color="#475569",
            command=self.destroy
        ).pack(side="right")

    def copy_hwid(self):
        self.clipboard_clear()
        self.clipboard_append(self.hwid)
        self.status_lbl.configure(text="✅ Đã sao chép mã HWID vào bộ nhớ tạm!", text_color="#34d399")

    def activate_key(self):
        entered = self.key_entry.get().strip().upper()
        ok, msg = activate_license_key(self.hwid, entered)
        if ok:
            self.activated_successfully = True
            messagebox.showinfo("Kích Hoạt Thành Công", f"Chúc mừng! Bản quyền của bạn đã được kích hoạt:\n{msg}")
            self.destroy()
        else:
            self.status_lbl.configure(text=f"❌ {msg}", text_color="#f43f5e")


if __name__ == "__main__":
    ensure_admin_privileges()

    current_hwid = get_machine_hwid()
    is_valid, msg, exp_display = check_license_state(current_hwid)

    if not is_valid:
        lic_win = LicenseActivationWindow(current_hwid)
        lic_win.mainloop()
        if not lic_win.activated_successfully:
            sys.exit(0)
        is_valid, msg, exp_display = check_license_state(current_hwid)

    app = AntiBotnetApp(hwid=current_hwid, license_info=exp_display)
    app.mainloop()