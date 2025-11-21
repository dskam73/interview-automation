import streamlit as st
import anthropic
import openai
import tempfile
import time
from datetime import datetime, timedelta, timezone
import zipfile
import io
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import subprocess
import json
import re
import urllib.request

# 문서 생성용
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# 페이지 설정 - 사이드바 숨김
st.set_page_config(
    page_title="캐피 인터뷰",
    page_icon="🎀",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ============================================
# 한국 표준시 (KST) 설정
# ============================================
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """한국 표준시 현재 시간 반환"""
    return datetime.now(KST)

# ============================================
# CSS 스타일 - 사이드바 완전 숨김 + 미니멀 디자인
# ============================================
st.markdown("""
<style>
/* 사이드바 완전 숨김 */
[data-testid="stSidebar"] {
    display: none;
}
[data-testid="collapsedControl"] {
    display: none;
}

/* 메인 컨테이너 */
.main .block-container {
    max-width: 700px;
    padding: 2rem 1rem;
}

/* 다운로드 버튼 */
.stDownloadButton > button {
    background-color: #4CAF50;
    color: white;
}

/* 파일 업로더 간소화 */
.stFileUploader > div {
    padding: 0.5rem;
}
</style>
""", unsafe_allow_html=True)

# ============================================
# 설정 상수
# ============================================
MAX_FILES_PER_UPLOAD = 5
DAILY_LIMIT_AUDIO = 30
DAILY_LIMIT_TEXT = 30
MAX_FILE_SIZE_MB = 20
USAGE_FILE = "/tmp/cappy_usage.json"
DOWNLOAD_DIR = "/tmp/cappy_downloads"
METADATA_FILE = "/tmp/cappy_downloads/metadata.json"
EXPIRY_HOURS = 24
DOCX_FONT_NAME = 'LG스마트체 Regular'
ADMIN_EMAIL_BCC = "dskam@lgbr.co.kr"
USD_TO_KRW = 1400

# ============================================
# 사용량 관리
# ============================================
def get_daily_usage():
    try:
        if not os.path.exists(USAGE_FILE):
            return {'audio': 0, 'text': 0, 'date': get_kst_now().strftime('%Y-%m-%d')}
        with open(USAGE_FILE, 'r') as f:
            usage = json.load(f)
        today = get_kst_now().strftime('%Y-%m-%d')
        if usage.get('date') != today:
            usage = {'audio': 0, 'text': 0, 'date': today}
            with open(USAGE_FILE, 'w') as f:
                json.dump(usage, f)
        return usage
    except:
        return {'audio': 0, 'text': 0, 'date': get_kst_now().strftime('%Y-%m-%d')}

def update_usage(file_type, count):
    try:
        usage = get_daily_usage()
        usage[file_type] = usage.get(file_type, 0) + count
        with open(USAGE_FILE, 'w') as f:
            json.dump(usage, f)
    except:
        pass

def check_usage_limit(file_type, count):
    usage = get_daily_usage()
    current = usage.get(file_type, 0)
    limit = DAILY_LIMIT_AUDIO if file_type == 'audio' else DAILY_LIMIT_TEXT
    remaining = limit - current
    return {'can_process': remaining > 0, 'remaining': remaining, 'allowed': min(count, remaining)}

# ============================================
# 다운로드 히스토리 관리
# ============================================
def init_download_system():
    try:
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        if not os.path.exists(METADATA_FILE):
            with open(METADATA_FILE, 'w') as f:
                json.dump([], f)
    except:
        pass

def save_download_file(zip_data, display_name, original_filename):
    try:
        init_download_system()
        now = get_kst_now()
        file_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{original_filename}"
        file_path = os.path.join(DOWNLOAD_DIR, file_id)
        with open(file_path, 'wb') as f:
            f.write(zip_data)
        
        metadata = []
        if os.path.exists(METADATA_FILE):
            try:
                with open(METADATA_FILE, 'r') as f:
                    metadata = json.load(f)
            except:
                pass
        
        # 만료된 파일 정리
        current_time = now
        valid_metadata = []
        for item in metadata:
            try:
                expiry = datetime.fromisoformat(item['expiry_time'])
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=KST)
                if current_time < expiry:
                    valid_metadata.append(item)
                else:
                    old_path = os.path.join(DOWNLOAD_DIR, item['file_id'])
                    if os.path.exists(old_path):
                        os.remove(old_path)
            except:
                continue
        
        new_item = {
            'file_id': file_id,
            'display_name': display_name,
            'original_filename': original_filename,
            'created_time': now.isoformat(),
            'expiry_time': (now + timedelta(hours=EXPIRY_HOURS)).isoformat(),
            'created_display': now.strftime('%m/%d %H:%M')
        }
        valid_metadata.insert(0, new_item)
        valid_metadata = valid_metadata[:10]
        
        with open(METADATA_FILE, 'w') as f:
            json.dump(valid_metadata, f)
        return True
    except:
        return False

def get_download_history():
    try:
        init_download_system()
        if not os.path.exists(METADATA_FILE):
            return []
        with open(METADATA_FILE, 'r') as f:
            metadata = json.load(f)
        current_time = get_kst_now()
        valid_items = []
        for item in metadata:
            try:
                expiry = datetime.fromisoformat(item['expiry_time'])
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=KST)
                if current_time < expiry:
                    remaining = expiry - current_time
                    hours = int(remaining.total_seconds() // 3600)
                    item['remaining'] = f"{hours}시간"
                    valid_items.append(item)
            except:
                continue
        return valid_items
    except:
        return []

def get_download_file(file_id):
    try:
        file_path = os.path.join(DOWNLOAD_DIR, file_id)
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                return f.read()
    except:
        pass
    return None

# ============================================
# 오디오 처리
# ============================================
def get_audio_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        info = json.loads(result.stdout)
        return float(info['format']['duration'])
    except:
        return None

def split_audio_file(audio_file, max_size_mb=20):
    try:
        file_size_mb = audio_file.size / (1024 * 1024)
        if file_size_mb <= max_size_mb:
            return None
        
        temp_dir = tempfile.mkdtemp()
        ext = audio_file.name.split('.')[-1].lower()
        input_path = os.path.join(temp_dir, f"input.{ext}")
        with open(input_path, 'wb') as f:
            f.write(audio_file.read())
        audio_file.seek(0)
        
        total_duration = get_audio_duration(input_path)
        if not total_duration:
            return None
        
        num_chunks = int(file_size_mb / max_size_mb) + 1
        chunk_duration = max(60, min(total_duration / num_chunks, 1200))
        
        chunks = []
        start = 0
        idx = 1
        while start < total_duration:
            end = min(start + chunk_duration, total_duration)
            out_path = os.path.join(temp_dir, f"chunk_{idx:03d}.mp3")
            cmd = ['ffmpeg', '-y', '-i', input_path, '-ss', str(start), '-t', str(chunk_duration),
                   '-acodec', 'libmp3lame', '-ab', '128k', '-ar', '44100', '-ac', '1', out_path]
            subprocess.run(cmd, capture_output=True, check=True)
            with open(out_path, 'rb') as f:
                chunks.append({'index': idx, 'start': start, 'end': end, 'data': io.BytesIO(f.read())})
            os.unlink(out_path)
            start = end
            idx += 1
        
        os.unlink(input_path)
        os.rmdir(temp_dir)
        return chunks
    except:
        return None

def transcribe_audio(audio_file, task="transcribe"):
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            return None, 0
        client = openai.OpenAI(api_key=api_key)
        file_size_mb = audio_file.size / (1024 * 1024)
        
        if file_size_mb > MAX_FILE_SIZE_MB:
            chunks = split_audio_file(audio_file, MAX_FILE_SIZE_MB)
            if not chunks:
                return None, 0
            
            all_text = []
            total_duration = chunks[-1]['end']
            for chunk in chunks:
                chunk['data'].seek(0)
                try:
                    if task == "translate":
                        result = client.audio.translations.create(model="whisper-1", file=("chunk.mp3", chunk['data'], "audio/mpeg"))
                    else:
                        result = client.audio.transcriptions.create(model="whisper-1", file=("chunk.mp3", chunk['data'], "audio/mpeg"))
                    all_text.append(result.text)
                except:
                    continue
            return "\n\n".join(all_text), total_duration
        else:
            ext = audio_file.name.split('.')[-1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
                tmp.write(audio_file.read())
                tmp_path = tmp.name
            audio_file.seek(0)
            duration = get_audio_duration(tmp_path) or 0
            
            with open(tmp_path, 'rb') as f:
                if task == "translate":
                    result = client.audio.translations.create(model="whisper-1", file=f)
                else:
                    result = client.audio.transcriptions.create(model="whisper-1", file=f)
            os.unlink(tmp_path)
            return result.text, duration
    except:
        return None, 0

# ============================================
# Claude 처리
# ============================================
def process_with_claude(content, prompt, task_name):
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None, 0, 0
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16000,
            temperature=0,
            messages=[{"role": "user", "content": f"{prompt}\n\n# 처리할 인터뷰 내용:\n\n{content}"}]
        )
        return message.content[0].text, message.usage.input_tokens, message.usage.output_tokens
    except:
        return None, 0, 0

# ============================================
# 파일 처리 유틸리티
# ============================================
def read_file(uploaded_file):
    try:
        content = uploaded_file.read().decode('utf-8')
        uploaded_file.seek(0)
        return content
    except:
        try:
            uploaded_file.seek(0)
            content = uploaded_file.read().decode('utf-8-sig')
            uploaded_file.seek(0)
            return content
        except:
            return None

def extract_header_from_transcript(text):
    header = {'title': '', 'date': '', 'participants': ''}
    if not text:
        return header
    for line in text.split('\n')[:20]:
        if line.startswith('# ') and not header['title']:
            header['title'] = line[2:].replace(' Full Transcript', '').strip()
        if '일시:' in line:
            match = re.search(r'[:\s]+(.+)$', line)
            if match:
                header['date'] = match.group(1).strip().replace('**', '')
        if '참석자:' in line:
            match = re.search(r'[:\s]+(.+)$', line)
            if match:
                header['participants'] = match.group(1).strip().replace('**', '')
    return header

def add_header_to_summary(summary, header):
    if not summary:
        return summary
    if summary.strip().startswith('# '):
        return normalize_markdown(summary)
    lines = []
    if header['title']:
        lines.append(f"# {header['title']} Summary")
    if header['date']:
        lines.append(f"**일시:** {header['date']}")
    if header['participants']:
        lines.append(f"**참석자:** {header['participants']}")
    if lines:
        lines.extend(["", "---", ""])
        return normalize_markdown('\n'.join(lines) + summary)
    return normalize_markdown(summary)

def normalize_markdown(text):
    if not text:
        return text
    section_kw = ['[요약]', '[핵심포인트]', '[핵심 포인트]', '[새롭게', '[인터뷰이가', '[답을', '[기업 사례]', '[유망', '[시사점]', '[핵심 코멘트]', '[주요 통계]', '[tags]']
    lines = []
    for line in text.split('\n'):
        if line.startswith('## ') and not any(kw in line for kw in section_kw):
            lines.append('###' + line[2:])
        else:
            lines.append(line)
    return '\n'.join(lines)

# ============================================
# DOCX 생성
# ============================================
def set_docx_font(run, font_name=DOCX_FONT_NAME, size=11):
    run.font.name = font_name
    run.font.size = Pt(size)
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn('w:eastAsia'), font_name)

def create_docx(content, title="문서"):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = DOCX_FONT_NAME
    style.font.size = Pt(11)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
    
    title_para = doc.add_heading(title, 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title_para.runs:
        set_docx_font(run, DOCX_FONT_NAME, 18)
    
    for line in content.split('\n'):
        s = line.strip()
        if s.startswith('# '):
            h = doc.add_heading(s[2:], 1)
            for r in h.runs: set_docx_font(r, DOCX_FONT_NAME, 16)
        elif s.startswith('## '):
            h = doc.add_heading(s[3:], 2)
            for r in h.runs: set_docx_font(r, DOCX_FONT_NAME, 14)
        elif s.startswith('### '):
            h = doc.add_heading(s[4:], 3)
            for r in h.runs: set_docx_font(r, DOCX_FONT_NAME, 12)
        elif s.startswith('#### '):
            h = doc.add_heading(s[5:], 4)
            for r in h.runs: set_docx_font(r, DOCX_FONT_NAME, 11)
        elif s.startswith('- ') or s.startswith('* '):
            p = doc.add_paragraph(s[2:], style='List Bullet')
            for r in p.runs: set_docx_font(r, DOCX_FONT_NAME, 11)
        elif s.startswith('---'):
            p = doc.add_paragraph('─' * 50)
            for r in p.runs: set_docx_font(r, DOCX_FONT_NAME, 11)
        elif s.startswith('**') and s.endswith('**'):
            p = doc.add_paragraph()
            r = p.add_run(s.strip('*'))
            r.bold = True
            set_docx_font(r, DOCX_FONT_NAME, 11)
        elif s:
            p = doc.add_paragraph()
            for part in re.split(r'(\*\*[^*]+\*\*)', s):
                if part.startswith('**') and part.endswith('**'):
                    r = p.add_run(part[2:-2])
                    r.bold = True
                else:
                    r = p.add_run(part)
                set_docx_font(r, DOCX_FONT_NAME, 11)
    
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ============================================
# ZIP 및 이메일
# ============================================
def generate_zip_filename(emails, source):
    email_id = emails[0].split('@')[0] if emails and '@' in emails[0] else ""
    date_str = get_kst_now().strftime('%y%m%d')
    base = source.rsplit('.', 1)[0] if '.' in source else source
    name = f"{email_id}{date_str}+{base}.zip" if email_id else f"interview_{date_str}+{base}.zip"
    return name.replace(' ', '_')

def send_email(to_emails, subject, body, attachments=None):
    try:
        gmail_user = st.secrets.get("gmail_user")
        gmail_password = st.secrets.get("gmail_password")
        if not gmail_user or not gmail_password:
            return False, "이메일 설정 없음"
        
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = ", ".join(to_emails)
        msg['Bcc'] = ADMIN_EMAIL_BCC
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        if attachments:
            for fname, data in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{fname}"')
                msg.attach(part)
        
        all_recipients = to_emails + [ADMIN_EMAIL_BCC]
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, all_recipients, msg.as_string())
        server.quit()
        return True, "전송 완료"
    except Exception as e:
        return False, str(e)

def calculate_costs(audio_min=0, in_tok=0, out_tok=0):
    whisper = audio_min * 0.006
    claude = (in_tok / 1_000_000) * 3.0 + (out_tok / 1_000_000) * 15.0
    total_krw = (whisper + claude) * USD_TO_KRW
    return {'total_krw': total_krw, 'whisper_usd': whisper, 'claude_usd': claude}

# ============================================
# 비밀번호 체크
# ============================================
def check_password():
    def entered():
        if st.session_state["pw"] == st.secrets.get("app_password", "interview2024"):
            st.session_state["auth"] = True
            del st.session_state["pw"]
        else:
            st.session_state["auth"] = False
    
    if "auth" not in st.session_state:
        st.markdown("## 🔐 접근 제한")
        st.text_input("비밀번호", type="password", on_change=entered, key="pw")
        return False
    elif not st.session_state["auth"]:
        st.markdown("## 🔐 접근 제한")
        st.text_input("비밀번호", type="password", on_change=entered, key="pw")
        st.error("❌ 비밀번호가 틀렸습니다.")
        return False
    return True

# ============================================
# 진행 단계 표시
# ============================================
def show_progress_steps(current_step, is_audio=True):
    if is_audio:
        steps = ["받아쓰기", "노트정리", "요약", "파일생성", "완료"]
    else:
        steps = ["읽기", "노트정리", "요약", "파일생성", "완료"]
    
    cols = st.columns(len(steps) * 2 - 1)
    for i, step in enumerate(steps):
        col_idx = i * 2
        with cols[col_idx]:
            if i < current_step:
                st.markdown(f"<div style='text-align:center;color:#51cf66'>✓ {step}</div>", unsafe_allow_html=True)
            elif i == current_step:
                st.markdown(f"<div style='text-align:center;color:#ff6b6b;font-weight:bold'>● {step}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='text-align:center;color:#aaa'>○ {step}</div>", unsafe_allow_html=True)
        if i < len(steps) - 1:
            with cols[col_idx + 1]:
                st.markdown("<div style='text-align:center;color:#ddd'>→</div>", unsafe_allow_html=True)

# ============================================
# 메인 앱
# ============================================
def main():
    if not check_password():
        return
    
    # 헤더
    st.markdown("# 🎀 캐피 인터뷰")
    st.markdown("인터뷰를 정리하는 캐피입니다. **음원**이나 **텍스트 파일**을 올려주세요.")
    
    # 프롬프트 로드
    try:
        transcript_prompt = st.secrets.get("transcript_prompt", "")
        summary_prompt = st.secrets.get("summary_prompt", "")
    except:
        transcript_prompt = ""
        summary_prompt = ""
    
    # 세션 상태 초기화
    if 'step' not in st.session_state:
        st.session_state.step = 'upload'
    
    st.markdown("---")
    
    # ========== STEP 1: 파일 업로드 ==========
    if st.session_state.step == 'upload':
        # 파일 업로더
        uploaded_files = st.file_uploader(
            "파일 선택",
            type=['mp3', 'wav', 'm4a', 'ogg', 'webm', 'txt', 'md'],
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        
        if uploaded_files:
            # 파일 타입 감지
            audio_exts = ['mp3', 'wav', 'm4a', 'ogg', 'webm']
            text_exts = ['txt', 'md']
            
            is_audio = any(f.name.split('.')[-1].lower() in audio_exts for f in uploaded_files)
            is_text = any(f.name.split('.')[-1].lower() in text_exts for f in uploaded_files)
            
            if is_audio and is_text:
                st.warning("⚠️ 음성 파일과 텍스트 파일을 섞어서 올릴 수 없어요. 한 종류만 올려주세요.")
            else:
                file_type = 'audio' if is_audio else 'text'
                
                # 제한 체크
                usage = check_usage_limit(file_type, len(uploaded_files))
                if not usage['can_process']:
                    st.error(f"⚠️ 오늘 처리 한도에 도달했어요. 내일 이용해주세요!")
                else:
                    files = uploaded_files[:min(MAX_FILES_PER_UPLOAD, usage['allowed'])]
                    if len(uploaded_files) > len(files):
                        st.info(f"💡 {len(files)}개만 처리됩니다. (한도: {MAX_FILES_PER_UPLOAD}개/회, 남은 한도: {usage['remaining']}개/일)")
                    
                    total_size = sum(f.size for f in files) / 1024 / 1024
                    st.caption(f"✅ {len(files)}개 파일 · {total_size:.1f} MB")
                    
                    st.markdown("---")
                    
                    # 옵션 선택
                    st.markdown("### ⚙️ 옵션 선택")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**정리 옵션**")
                        if is_audio:
                            do_transcript = st.checkbox("노트 정리", value=True)
                        else:
                            do_transcript = st.checkbox("풀 트랜스크립트", value=True)
                        do_summary = st.checkbox("요약문 작성", value=False)
                    
                    with col2:
                        st.markdown("**출력 형식**")
                        out_md = st.checkbox("Markdown", value=True)
                        out_docx = st.checkbox("Word", value=True)
                        out_txt = st.checkbox("Text", value=False)
                    
                    st.markdown("**이메일 발송**")
                    email_input = st.text_input("받는 사람 (콤마로 구분)", placeholder="user@company.com")
                    emails = [e.strip() for e in email_input.split(',') if e.strip() and '@' in e][:5]
                    
                    st.markdown("---")
                    
                    if st.button("🚀 시작", type="primary", use_container_width=True):
                        st.session_state.files = files
                        st.session_state.file_type = file_type
                        st.session_state.do_transcript = do_transcript
                        st.session_state.do_summary = do_summary
                        st.session_state.out_md = out_md
                        st.session_state.out_docx = out_docx
                        st.session_state.out_txt = out_txt
                        st.session_state.emails = emails
                        st.session_state.step = 'processing'
                        st.rerun()
        
        # 기존 작업물 다운로드
        st.markdown("---")
        history = get_download_history()
        if history:
            st.markdown("### 📥 최근 작업물")
            for item in history[:5]:
                data = get_download_file(item['file_id'])
                if data:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.caption(f"{item['display_name']} ({item['created_display']}, {item['remaining']} 남음)")
                    with col2:
                        st.download_button("📦", data, item['original_filename'], "application/zip", key=item['file_id'])
    
    # ========== STEP 2: 처리 중 ==========
    elif st.session_state.step == 'processing':
        files = st.session_state.files
        file_type = st.session_state.file_type
        is_audio = file_type == 'audio'
        
        total_files = len(files)
        results = []
        total_audio_min = 0
        total_in_tok = 0
        total_out_tok = 0
        start_time = time.time()
        
        for idx, f in enumerate(files):
            base_name = f.name.rsplit('.', 1)[0]
            st.markdown(f"### 📄 {f.name} ({idx+1}/{total_files})")
            
            progress_placeholder = st.empty()
            status_placeholder = st.empty()
            
            result = {'filename': f.name, 'base_name': base_name, 'whisper': None, 'transcript': None, 'summary': None}
            
            # Step 0/1: 받아쓰기 또는 읽기
            with progress_placeholder:
                show_progress_steps(0, is_audio)
            
            if is_audio:
                status_placeholder.caption("🎧 받아쓰는 중...")
                text, duration = transcribe_audio(f)
                total_audio_min += (duration or 0) / 60
                result['whisper'] = text
                source_text = text
            else:
                status_placeholder.caption("📖 파일 읽는 중...")
                source_text = read_file(f)
            
            if not source_text:
                status_placeholder.error("❌ 파일 처리 실패")
                continue
            
            # Step 1/2: 노트정리
            if st.session_state.do_transcript and transcript_prompt:
                with progress_placeholder:
                    show_progress_steps(1, is_audio)
                status_placeholder.caption("📝 노트 정리 중...")
                transcript, in_t, out_t = process_with_claude(source_text, transcript_prompt, "노트정리")
                result['transcript'] = transcript
                total_in_tok += in_t
                total_out_tok += out_t
                source_text = transcript or source_text
            
            # Step 2/3: 요약
            if st.session_state.do_summary and summary_prompt:
                with progress_placeholder:
                    show_progress_steps(2, is_audio)
                status_placeholder.caption("📋 요약 작성 중...")
                summary, in_t, out_t = process_with_claude(source_text, summary_prompt, "요약")
                if summary and result['transcript']:
                    header = extract_header_from_transcript(result['transcript'])
                    summary = add_header_to_summary(summary, header)
                result['summary'] = summary
                total_in_tok += in_t
                total_out_tok += out_t
            
            # Step 3: 파일생성
            with progress_placeholder:
                show_progress_steps(3, is_audio)
            status_placeholder.caption("📁 파일 생성 중...")
            
            results.append(result)
            
            # Step 4: 완료
            with progress_placeholder:
                show_progress_steps(4, is_audio)
            status_placeholder.success("✅ 완료")
            time.sleep(0.3)
            progress_placeholder.empty()
            status_placeholder.empty()
        
        elapsed = time.time() - start_time
        
        # 결과 저장
        st.session_state.results = results
        st.session_state.total_audio_min = total_audio_min
        st.session_state.total_in_tok = total_in_tok
        st.session_state.total_out_tok = total_out_tok
        st.session_state.elapsed = elapsed
        st.session_state.step = 'done'
        st.rerun()
    
    # ========== STEP 3: 완료 ==========
    elif st.session_state.step == 'done':
        results = st.session_state.results
        emails = st.session_state.emails
        
        costs = calculate_costs(
            st.session_state.total_audio_min,
            st.session_state.total_in_tok,
            st.session_state.total_out_tok
        )
        
        # ZIP 생성
        first_name = results[0]['filename'] if results else "interview"
        zip_filename = generate_zip_filename(emails, first_name)
        
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for r in results:
                base = r['base_name']
                
                # Whisper 원본
                if r.get('whisper'):
                    zf.writestr(f"{base}_whisper.txt", r['whisper'])
                
                # 트랜스크립트 - 원본 파일명
                if r.get('transcript'):
                    if st.session_state.out_md:
                        zf.writestr(f"{base}.md", r['transcript'])
                    if st.session_state.out_docx:
                        docx = create_docx(r['transcript'], base)
                        zf.writestr(f"{base}.docx", docx.read())
                    if st.session_state.out_txt:
                        plain = re.sub(r'[#*_\-]+', '', r['transcript'])
                        zf.writestr(f"{base}.txt", re.sub(r'\n{3,}', '\n\n', plain))
                
                # 요약문 - #prefix
                if r.get('summary'):
                    if st.session_state.out_md:
                        zf.writestr(f"#{base}.md", r['summary'])
                    if st.session_state.out_docx:
                        docx = create_docx(r['summary'], f"#{base}")
                        zf.writestr(f"#{base}.docx", docx.read())
                    if st.session_state.out_txt:
                        plain = re.sub(r'[#*_\-]+', '', r['summary'])
                        zf.writestr(f"#{base}.txt", re.sub(r'\n{3,}', '\n\n', plain))
        
        zip_buf.seek(0)
        zip_data = zip_buf.getvalue()
        
        # 히스토리 저장
        display = f"{first_name}" if len(results) == 1 else f"{first_name} 외 {len(results)-1}개"
        save_download_file(zip_data, display, zip_filename)
        
        # 사용량 업데이트
        update_usage(st.session_state.file_type, len(results))
        
        # 이메일 발송
        email_sent = False
        if emails:
            minutes = int(st.session_state.elapsed // 60)
            seconds = int(st.session_state.elapsed % 60)
            body = f"""안녕하세요! 캐피입니다 😊

인터뷰 정리 결과를 공유드립니다.

• 처리 파일: {len(results)}개
• 소요 시간: {minutes}분 {seconds}초
• 처리 비용: 약 {costs['total_krw']:,.0f}원

첨부파일을 확인해주세요!

───────────────────────────
🎀 캐피 인터뷰
"""
            success, _ = send_email(emails, f"[캐피 인터뷰] 인터뷰 정리 결과 - {get_kst_now().strftime('%Y-%m-%d')}", body, [(zip_filename, zip_data)])
            email_sent = success
        
        # 결과 표시
        st.markdown("## ✅ 작업 완료!")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            m = int(st.session_state.elapsed // 60)
            s = int(st.session_state.elapsed % 60)
            st.metric("⏱️ 소요 시간", f"{m}분 {s}초")
        with col2:
            st.metric("📄 처리 파일", f"{len(results)}개")
        with col3:
            st.metric("💰 비용", f"₩{costs['total_krw']:,.0f}")
        
        if emails:
            if email_sent:
                st.success(f"📧 이메일 발송 완료: {', '.join(emails)}")
            else:
                st.warning("⚠️ 이메일 발송 실패")
        
        st.markdown("---")
        
        st.download_button(
            "📦 다운로드",
            zip_data,
            zip_filename,
            "application/zip",
            use_container_width=True
        )
        
        st.markdown("---")
        
        if st.button("🔄 새 작업 시작", use_container_width=True):
            for key in ['step', 'files', 'file_type', 'do_transcript', 'do_summary', 
                       'out_md', 'out_docx', 'out_txt', 'emails', 'results',
                       'total_audio_min', 'total_in_tok', 'total_out_tok', 'elapsed']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

if __name__ == "__main__":
    main()
