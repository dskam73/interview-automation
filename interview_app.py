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
import threading
import queue
from pathlib import Path
import hashlib

# 문서 생성용
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

# ============================================
# 페이지 설정
# ============================================
st.set_page_config(
    page_title="캐피 인터뷰",
    page_icon="😊",
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
# CSS 스타일
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

/* 진행 표시 */
.progress-step {
    display: inline-block;
    padding: 0.5rem 1rem;
    margin: 0.2rem;
    border-radius: 5px;
    font-size: 0.9rem;
}
.step-pending { background: #f0f0f0; color: #999; }
.step-active { background: #ff6b6b; color: white; font-weight: bold; }
.step-done { background: #51cf66; color: white; }
</style>
""", unsafe_allow_html=True)

# ============================================
# 설정 상수
# ============================================
MAX_FILES_PER_UPLOAD = 5
DAILY_LIMIT_AUDIO = 30
DAILY_LIMIT_TEXT = 30
MAX_FILE_SIZE_MB = 25
USAGE_FILE = "/tmp/cappy_usage.json"
DOWNLOAD_DIR = "/tmp/cappy_downloads"
METADATA_FILE = "/tmp/cappy_downloads/metadata.json"
EXPIRY_HOURS = 24
DOCX_FONT_NAME = 'LG스마트체 Regular'
ADMIN_EMAIL_BCC = "dskam@lgbr.co.kr"
USD_TO_KRW = 1400

# Job Queue 설정
JOB_DIR = "/tmp/cappy_jobs"
HEARTBEAT_INTERVAL = 3  # 3초마다 상태 체크

# ============================================
# Job Queue 시스템
# ============================================
def init_job_system():
    """Job 디렉토리 초기화"""
    try:
        if not os.path.exists(JOB_DIR):
            os.makedirs(JOB_DIR, exist_ok=True)
    except Exception as e:
        st.error(f"Job 시스템 초기화 실패: {e}")

def create_job_id():
    """고유 Job ID 생성"""
    timestamp = get_kst_now().strftime('%Y%m%d_%H%M%S')
    random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    return f"{timestamp}_{random_hash}"

def get_job_dir(job_id):
    """Job 디렉토리 경로"""
    return os.path.join(JOB_DIR, job_id)

def save_job_state(job_id, state):
    """Job 상태 저장"""
    try:
        job_dir = get_job_dir(job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        state['updated_at'] = get_kst_now().isoformat()
        
        state_file = os.path.join(job_dir, 'state.json')
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Job 상태 저장 실패: {e}")
        return False

def load_job_state(job_id):
    """Job 상태 로드"""
    try:
        state_file = os.path.join(get_job_dir(job_id), 'state.json')
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"Job 상태 로드 실패: {e}")
        return None

def save_file_result(job_id, filename, result_type, content):
    """파일별 결과 저장"""
    try:
        job_dir = get_job_dir(job_id)
        result_dir = os.path.join(job_dir, 'results')
        os.makedirs(result_dir, exist_ok=True)
        
        safe_filename = re.sub(r'[^\w\-_.]', '_', filename)
        result_file = os.path.join(result_dir, f"{safe_filename}_{result_type}.txt")
        
        with open(result_file, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"파일 결과 저장 실패: {e}")
        return False

def load_file_result(job_id, filename, result_type):
    """파일별 결과 로드"""
    try:
        safe_filename = re.sub(r'[^\w\-_.]', '_', filename)
        result_file = os.path.join(get_job_dir(job_id), 'results', f"{safe_filename}_{result_type}.txt")
        
        if os.path.exists(result_file):
            with open(result_file, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    except Exception as e:
        print(f"파일 결과 로드 실패: {e}")
        return None

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

def transcribe_audio(audio_file, task="transcribe", model="whisper-1"):
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            return None, 0
        client = openai.OpenAI(api_key=api_key)
        file_size_mb = audio_file.size / (1024 * 1024)
        
        if task == "translate":
            model = "whisper-1"
        
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
                        result = client.audio.transcriptions.create(model=model, file=("chunk.mp3", chunk['data'], "audio/mpeg"))
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
                    result = client.audio.transcriptions.create(model=model, file=f)
            os.unlink(tmp_path)
            return result.text, duration
    except Exception as e:
        print(f"Transcribe error: {e}")
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
    except Exception as e:
        print(f"Claude error: {e}")
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
def create_docx(content, title="문서"):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = DOCX_FONT_NAME
    style.font.size = Pt(11)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
    
    title_para = doc.add_heading(title, 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title_para.runs:
        run.font.name = DOCX_FONT_NAME
        run.font.size = Pt(18)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
    
    for line in content.split('\n'):
        s = line.strip()
        if s.startswith('# '):
            h = doc.add_heading(s[2:], 1)
            for r in h.runs:
                r.font.name = DOCX_FONT_NAME
                r.font.size = Pt(16)
                r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
        elif s.startswith('## '):
            h = doc.add_heading(s[3:], 2)
            for r in h.runs:
                r.font.name = DOCX_FONT_NAME
                r.font.size = Pt(14)
                r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
        elif s.startswith('### '):
            h = doc.add_heading(s[4:], 3)
            for r in h.runs:
                r.font.name = DOCX_FONT_NAME
                r.font.size = Pt(12)
                r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
        elif s.startswith('#### '):
            h = doc.add_heading(s[5:], 4)
            for r in h.runs:
                r.font.name = DOCX_FONT_NAME
                r.font.size = Pt(11)
                r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
        elif s.startswith('- ') or s.startswith('* '):
            p = doc.add_paragraph(s[2:], style='List Bullet')
            for r in p.runs:
                r.font.name = DOCX_FONT_NAME
                r.font.size = Pt(11)
                r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
        elif s.startswith('---'):
            p = doc.add_paragraph('─' * 50)
            for r in p.runs:
                r.font.name = DOCX_FONT_NAME
                r.font.size = Pt(11)
                r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
        elif s.startswith('**') and s.endswith('**'):
            p = doc.add_paragraph()
            r = p.add_run(s.strip('*'))
            r.bold = True
            r.font.name = DOCX_FONT_NAME
            r.font.size = Pt(11)
            r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
        elif s:
            p = doc.add_paragraph()
            for part in re.split(r'(\*\*[^*]+\*\*)', s):
                if part.startswith('**') and part.endswith('**'):
                    r = p.add_run(part[2:-2])
                    r.bold = True
                else:
                    r = p.add_run(part)
                r.font.name = DOCX_FONT_NAME
                r.font.size = Pt(11)
                r._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
    
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

def calculate_costs(audio_min=0, in_tok=0, out_tok=0, stt_model="whisper-1"):
    stt_rates = {
        "whisper-1": 0.006,
        "gpt-4o-transcribe": 0.006,
        "gpt-4o-mini-transcribe": 0.003
    }
    stt_rate = stt_rates.get(stt_model, 0.006)
    
    stt_cost = audio_min * stt_rate
    claude = (in_tok / 1_000_000) * 3.0 + (out_tok / 1_000_000) * 15.0
    total_krw = (stt_cost + claude) * USD_TO_KRW
    return {'total_krw': total_krw, 'stt_usd': stt_cost, 'claude_usd': claude}

def generate_email_body(results, files, file_type, do_transcript, do_summary, out_md, out_docx, out_txt, minutes, seconds, costs):
    is_audio = file_type == 'audio'
    file_type_label = "음성" if is_audio else "텍스트"
    
    input_list = []
    for idx, f in enumerate(files, 1):
        input_list.append(f"{idx}. {f.name} ({file_type_label})")
    input_section = "\n".join(input_list)
    
    output_list = []
    for idx, r in enumerate(results, 1):
        base = r['base_name']
        lines = [f"{idx}. {r['filename']} ({file_type_label})"]
        
        if r.get('whisper'):
            lines.append(f"   - 녹취(원본): {base}_whisper.txt")
        
        if r.get('transcript'):
            formats = []
            if out_docx:
                formats.append(f"{base}.docx")
            if out_md:
                formats.append(f"{base}.md")
            if out_txt:
                formats.append(f"{base}.txt")
            if formats:
                label = "녹취(번역/정리)" if is_audio else "트랜스크립트"
                lines.append(f"   - {label}: {', '.join(formats)}")
        
        if r.get('summary'):
            formats = []
            if out_docx:
                formats.append(f"#{base}.docx")
            if out_md:
                formats.append(f"#{base}.md")
            if out_txt:
                formats.append(f"#{base}.txt")
            if formats:
                lines.append(f"   - 요약: {', '.join(formats)}")
        
        output_list.append("\n".join(lines))
    
    output_section = "\n".join(output_list)
    
    tasks = []
    if is_audio:
        tasks.append("받아쓰기")
    if do_transcript:
        tasks.append("번역" if is_audio else "정리")
    if do_summary:
        tasks.append("요약")
    task_desc = ", ".join(tasks) if tasks else "정리"
    
    body = f"""안녕하세요! 캐피입니다 😊
인터뷰 정리 결과를 보내드립니다.

📄 다음 파일들을 제게 주셨어요 ({len(files)}개)
─────────────────────────────────────────────────
{input_section}

✅ 주신 파일별로 {task_desc}를 했습니다
─────────────────────────────────────────────────
{output_section}

※ 첨부파일을 확인해주세요!

💰 열심히 하고 있는데 그래도 이 만큼 걸리네요 ⏱️
─────────────────────────────────────────────────
• 소요 시간/비용: {minutes}분 {seconds}초 / 약 {costs['total_krw']:,.0f}원
"""
    return body

# ============================================
# 백그라운드 작업 처리 함수
# ============================================
def process_job_background(job_id, files_data, config):
    """백그라운드에서 실행될 작업 처리"""
    try:
        # Job 상태 초기화
        state = {
            'status': 'processing',
            'current_step': 'init',
            'current_file': '',
            'progress': 0,
            'total_files': len(files_data),
            'completed_files': 0,
            'results': {},
            'total_audio_min': 0,
            'total_in_tok': 0,
            'total_out_tok': 0,
            'start_time': time.time(),
            'error': None
        }
        save_job_state(job_id, state)
        
        # 프롬프트 로드
        transcript_prompt = config.get('transcript_prompt', '')
        summary_prompt = config.get('summary_prompt', '')
        
        # 각 파일 처리
        for idx, file_data in enumerate(files_data):
            filename = file_data['name']
            base_name = filename.rsplit('.', 1)[0]
            
            # 상태 업데이트
            state['current_file'] = filename
            state['current_step'] = 'transcribe' if config['is_audio'] else 'read'
            state['progress'] = int((idx / len(files_data)) * 100)
            save_job_state(job_id, state)
            
            result = {
                'filename': filename,
                'base_name': base_name,
                'whisper': None,
                'transcript': None,
                'summary': None
            }
            
            # 오디오 처리
            if config['is_audio']:
                # 임시 파일로 저장
                temp_file = io.BytesIO(file_data['content'])
                temp_file.name = filename
                temp_file.size = len(file_data['content'])
                
                text, duration = transcribe_audio(
                    temp_file, 
                    task=config['whisper_task'],
                    model=config['stt_model']
                )
                
                if text:
                    result['whisper'] = text
                    save_file_result(job_id, filename, 'whisper', text)
                    state['total_audio_min'] += (duration or 0) / 60
                    source_text = text
                else:
                    state['error'] = f"{filename} 전사 실패"
                    save_job_state(job_id, state)
                    continue
            else:
                # 텍스트 파일
                source_text = file_data['content'].decode('utf-8')
            
            # 트랜스크립트 작성
            if config['do_transcript'] and transcript_prompt:
                state['current_step'] = 'transcript'
                save_job_state(job_id, state)
                
                transcript, in_tok, out_tok = process_with_claude(
                    source_text,
                    transcript_prompt,
                    "트랜스크립트"
                )
                
                if transcript:
                    result['transcript'] = transcript
                    save_file_result(job_id, filename, 'transcript', transcript)
                    state['total_in_tok'] += in_tok
                    state['total_out_tok'] += out_tok
                    source_text = transcript
            
            # 요약 작성
            if config['do_summary'] and summary_prompt:
                state['current_step'] = 'summary'
                save_job_state(job_id, state)
                
                summary, in_tok, out_tok = process_with_claude(
                    source_text,
                    summary_prompt,
                    "요약문"
                )
                
                if summary and result.get('transcript'):
                    header = extract_header_from_transcript(result['transcript'])
                    summary = add_header_to_summary(summary, header)
                
                if summary:
                    result['summary'] = summary
                    save_file_result(job_id, filename, 'summary', summary)
                    state['total_in_tok'] += in_tok
                    state['total_out_tok'] += out_tok
            
            # 결과 저장
            state['results'][filename] = result
            state['completed_files'] = idx + 1
            save_job_state(job_id, state)
        
        # ZIP 파일 생성
        state['current_step'] = 'zip'
        save_job_state(job_id, state)
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename, result in state['results'].items():
                base = result['base_name']
                
                if result.get('whisper'):
                    zf.writestr(f"{base}_whisper.txt", result['whisper'])
                
                if result.get('transcript'):
                    if config['out_md']:
                        zf.writestr(f"{base}.md", result['transcript'])
                    if config['out_docx']:
                        docx = create_docx(result['transcript'], base)
                        zf.writestr(f"{base}.docx", docx.read())
                    if config['out_txt']:
                        plain = re.sub(r'[#*_\-]+', '', result['transcript'])
                        zf.writestr(f"{base}.txt", re.sub(r'\n{3,}', '\n\n', plain))
                
                if result.get('summary'):
                    if config['out_md']:
                        zf.writestr(f"#{base}.md", result['summary'])
                    if config['out_docx']:
                        docx = create_docx(result['summary'], f"#{base}")
                        zf.writestr(f"#{base}.docx", docx.read())
                    if config['out_txt']:
                        plain = re.sub(r'[#*_\-]+', '', result['summary'])
                        zf.writestr(f"#{base}.txt", re.sub(r'\n{3,}', '\n\n', plain))
        
        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()
        
        # ZIP 저장
        zip_path = os.path.join(get_job_dir(job_id), 'result.zip')
        with open(zip_path, 'wb') as f:
            f.write(zip_data)
        
        # 이메일 발송
        if config.get('emails'):
            state['current_step'] = 'email'
            save_job_state(job_id, state)
            
            elapsed = time.time() - state['start_time']
            costs = calculate_costs(
                state['total_audio_min'],
                state['total_in_tok'],
                state['total_out_tok'],
                config['stt_model']
            )
            
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            body = generate_email_body(
                list(state['results'].values()),
                [{'name': fd['name']} for fd in files_data],
                'audio' if config['is_audio'] else 'text',
                config['do_transcript'],
                config['do_summary'],
                config['out_md'],
                config['out_docx'],
                config['out_txt'],
                minutes,
                seconds,
                costs
            )
            
            first_filename = files_data[0]['name']
            zip_filename = generate_zip_filename(config['emails'], first_filename)
            
            send_email(
                config['emails'],
                f"[캐피 인터뷰] 인터뷰 정리 결과 - {get_kst_now().strftime('%Y-%m-%d')}",
                body,
                [(zip_filename, zip_data)]
            )
        
        # 완료 상태
        state['status'] = 'completed'
        state['current_step'] = 'done'
        state['progress'] = 100
        state['elapsed_time'] = time.time() - state['start_time']
        save_job_state(job_id, state)
        
        # 다운로드 히스토리 저장
        display = first_filename if len(files_data) == 1 else f"{first_filename} 외 {len(files_data)-1}개"
        save_download_file(zip_data, display, zip_filename)
        
        # 사용량 업데이트
        update_usage('audio' if config['is_audio'] else 'text', len(files_data))
        
    except Exception as e:
        state['status'] = 'error'
        state['error'] = str(e)
        save_job_state(job_id, state)

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
        st.markdown("## 🔒 접근 제한")
        st.text_input("비밀번호", type="password", on_change=entered, key="pw")
        return False
    elif not st.session_state["auth"]:
        st.markdown("## 🔒 접근 제한")
        st.text_input("비밀번호", type="password", on_change=entered, key="pw")
        st.error("❌ 비밀번호가 틀렸습니다.")
        return False
    return True

# ============================================
# 진행 상태 표시 함수
# ============================================
def show_progress_ui(job_state):
    """진행 상태를 시각적으로 표시"""
    if not job_state:
        return
    
    status = job_state.get('status', 'processing')
    current_step = job_state.get('current_step', '')
    current_file = job_state.get('current_file', '')
    progress = job_state.get('progress', 0)
    completed = job_state.get('completed_files', 0)
    total = job_state.get('total_files', 0)
    
    # 진행 단계 정의
    steps = ['init', 'transcribe', 'transcript', 'summary', 'zip', 'email', 'done']
    step_labels = {
        'init': '시작',
        'transcribe': '받아쓰기',
        'read': '파일읽기',
        'transcript': '노트정리',
        'summary': '요약',
        'zip': '파일생성',
        'email': '이메일',
        'done': '완료'
    }
    
    # 단계별 상태 표시
    step_html = ""
    for step in steps:
        if step == 'done':
            label = '완료'
            css_class = 'step-done' if status == 'completed' else 'step-pending'
        else:
            label = step_labels.get(step, step)
            if step == current_step or (step == 'transcribe' and current_step == 'read'):
                css_class = 'step-active'
            elif steps.index(step) < steps.index(current_step if current_step in steps else 'init'):
                css_class = 'step-done'
            else:
                css_class = 'step-pending'
        
        step_html += f'<span class="progress-step {css_class}">{label}</span>'
    
    st.markdown(step_html, unsafe_allow_html=True)
    
    # 진행률 표시
    st.progress(progress / 100)
    
    # 현재 작업 표시
    if current_file:
        st.caption(f"📄 처리 중: {current_file} ({completed}/{total})")
    
    # 에러 표시
    if job_state.get('error'):
        st.error(f"❌ 오류: {job_state['error']}")

# ============================================
# 메인 앱
# ============================================
def main():
    if not check_password():
        return
    
    # Job 시스템 초기화
    init_job_system()
    
    # 헤더
    st.markdown("# 😊 캐피 인터뷰")
    
    # 프롬프트 로드
    try:
        transcript_prompt = st.secrets.get("transcript_prompt", "")
        summary_prompt = st.secrets.get("summary_prompt", "")
    except:
        transcript_prompt = ""
        summary_prompt = ""
    
    # 진행 중인 Job이 있는지 확인
    active_job_id = st.session_state.get('active_job_id')
    
    if active_job_id:
        # Job 상태 로드
        job_state = load_job_state(active_job_id)
        
        if job_state and job_state['status'] == 'processing':
            # 진행 중 - 상태 표시
            st.markdown("꼼꼼하게 정리해 볼게요! 기대해 주세요 🔎")
            st.markdown("---")
            
            # 진행 상태 표시
            show_progress_ui(job_state)
            
            # 안내 메시지
            st.info("🔨 작업이 진행 중입니다! 화면을 닫아도 캐피는 계속 일해요 😊")
            
            # 자동 새로고침 (3초마다)
            time.sleep(HEARTBEAT_INTERVAL)
            st.rerun()
            
        elif job_state and job_state['status'] == 'completed':
            # 완료 - 결과 표시
            st.markdown("인터뷰를 정리하는 캐피입니다. 음원/텍스트를 올려주세요! 🔎")
            st.markdown("---")
            
            # 완료 상태 표시
            show_progress_ui(job_state)
            
            st.success("✅ 모든 작업이 완료되었습니다!")
            
            # 통계 표시
            elapsed = job_state.get('elapsed_time', 0)
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            config = st.session_state.get('job_config', {})
            costs = calculate_costs(
                job_state.get('total_audio_min', 0),
                job_state.get('total_in_tok', 0),
                job_state.get('total_out_tok', 0),
                config.get('stt_model', 'whisper-1')
            )
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("⏱️ 소요 시간", f"{minutes}분 {seconds}초")
            with col2:
                st.metric("📄 처리 파일", f"{job_state['total_files']}개")
            with col3:
                st.metric("💰 비용", f"₩{costs['total_krw']:,.0f}")
            
            # ZIP 다운로드
            zip_path = os.path.join(get_job_dir(active_job_id), 'result.zip')
            if os.path.exists(zip_path):
                with open(zip_path, 'rb') as f:
                    zip_data = f.read()
                
                first_file = list(job_state['results'].keys())[0] if job_state['results'] else 'interview'
                zip_filename = generate_zip_filename(config.get('emails', []), first_file)
                
                st.download_button(
                    "📦 바로 다운로드",
                    zip_data,
                    zip_filename,
                    "application/zip",
                    use_container_width=True
                )
            
            # 새 작업 버튼
            if st.button("🔄 새 작업 시작", use_container_width=True):
                del st.session_state['active_job_id']
                if 'job_config' in st.session_state:
                    del st.session_state['job_config']
                st.rerun()
            
            return
        
        elif job_state and job_state['status'] == 'error':
            # 에러 - 재시도 옵션
            st.markdown("인터뷰를 정리하는 캐피입니다. 음원/텍스트를 올려주세요! 🔎")
            st.markdown("---")
            
            st.error(f"❌ 작업 중 오류가 발생했습니다: {job_state.get('error', '알 수 없는 오류')}")
            
            if st.button("🔄 다시 시도", use_container_width=True):
                del st.session_state['active_job_id']
                if 'job_config' in st.session_state:
                    del st.session_state['job_config']
                st.rerun()
            
            return
    
    # 새 작업 시작 - 기존 UI 그대로
    st.markdown("인터뷰를 정리하는 캐피입니다. 음원/텍스트를 올려주세요! 🔎")
    st.markdown("---")
    
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
                st.error("⚠️ 오늘 처리 한도에 도달했어요. 내일 이용해주세요!")
            else:
                files = uploaded_files[:min(MAX_FILES_PER_UPLOAD, usage['allowed'])]
                if len(uploaded_files) > len(files):
                    st.info(f"💡 {len(files)}개만 처리됩니다. (한도: {MAX_FILES_PER_UPLOAD}개/회, 남은 한도: {usage['remaining']}개/일)")
                
                total_size = sum(f.size for f in files) / 1024 / 1024
                st.caption(f"✅ {len(files)}개 파일 · {total_size:.1f} MB")
                
                st.markdown("---")
                
                # 옵션 선택
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**📋 정리 옵션**")
                    if is_audio:
                        do_transcript = st.checkbox("노트 정리", value=True)
                    else:
                        do_transcript = st.checkbox("풀 트랜스크립트", value=True)
                    do_summary = st.checkbox("요약문 작성", value=False)
                
                with col2:
                    st.markdown("**📁 출력 형식**")
                    out_md = st.checkbox("Markdown", value=True)
                    out_docx = st.checkbox("Word", value=True)
                    out_txt = st.checkbox("Text", value=False)
                
                # 음성 파일일 때 모델 선택
                if is_audio:
                    st.markdown("---")
                    st.markdown("**🎤 음성 인식 모델**")
                    stt_model = st.radio(
                        "음성 인식 모델 선택",
                        options=["gpt-4o-transcribe", "whisper-1", "gpt-4o-mini-transcribe"],
                        format_func=lambda x: {
                            "gpt-4o-transcribe": "GPT-4o ($0.006/분) - 최고 정확도, 환각 감소",
                            "whisper-1": "Whisper ($0.006/분) - 안정적, 타임스탬프 지원",
                            "gpt-4o-mini-transcribe": "GPT-4o Mini ($0.003/분) - 50% 저렴, 빠름"
                        }[x],
                        index=0,
                        label_visibility="collapsed"
                    )
                    
                    whisper_task = st.radio(
                        "전사 방식",
                        ["원래 언어 그대로요", "영어로 번역해 주세요"],
                        label_visibility="collapsed"
                    )
                    whisper_task_value = "transcribe" if whisper_task == "원래 언어 그대로요" else "translate"
                else:
                    stt_model = "whisper-1"
                    whisper_task_value = "transcribe"
                
                st.markdown("---")
                
                # 이메일 입력 (필수)
                st.markdown("**📧 결과 받을 이메일** (필수)")
                email_input = st.text_input("이메일 주소 (콤마로 구분, 최대 5명)", placeholder="user@company.com", label_visibility="collapsed")
                emails = [e.strip() for e in email_input.split(',') if e.strip() and '@' in e][:5]
                
                if emails:
                    st.caption(f"📬 {len(emails)}명: {', '.join(emails)}")
                
                st.markdown("---")
                
                # 시작 버튼
                can_start = len(emails) > 0
                
                if not can_start:
                    st.warning("📧 결과를 받을 이메일을 입력해주세요.")
                
                if st.button("🚀 시작", type="primary", use_container_width=True, disabled=not can_start):
                    # Job 생성
                    job_id = create_job_id()
                    
                    # 파일 데이터 준비
                    files_data = []
                    for f in files:
                        files_data.append({
                            'name': f.name,
                            'content': f.read()
                        })
                        f.seek(0)
                    
                    # 설정 저장
                    config = {
                        'is_audio': is_audio,
                        'do_transcript': do_transcript,
                        'do_summary': do_summary,
                        'out_md': out_md,
                        'out_docx': out_docx,
                        'out_txt': out_txt,
                        'emails': emails,
                        'stt_model': stt_model,
                        'whisper_task': whisper_task_value,
                        'transcript_prompt': transcript_prompt,
                        'summary_prompt': summary_prompt
                    }
                    
                    # 세션에 저장
                    st.session_state['active_job_id'] = job_id
                    st.session_state['job_config'] = config
                    
                    # 백그라운드 작업 시작
                    thread = threading.Thread(
                        target=process_job_background,
                        args=(job_id, files_data, config),
                        daemon=True
                    )
                    thread.start()
                    
                    # 페이지 새로고침
                    st.rerun()
    
    # 기존 작업물 다운로드
    st.markdown("---")
    
    # 오늘의 사용량 표시
    usage = get_daily_usage()
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"🎤 음성: {usage.get('audio', 0)}/{DAILY_LIMIT_AUDIO}개")
    with col2:
        st.caption(f"📄 텍스트: {usage.get('text', 0)}/{DAILY_LIMIT_TEXT}개")
    
    st.markdown("### 📥 최근 작업물 (24시간)")
    history = get_download_history()
    if history:
        for item in history[:5]:
            data = get_download_file(item['file_id'])
            if data:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.caption(f"{item['display_name']} ({item['created_display']}, {item['remaining']} 남음)")
                with col2:
                    st.download_button("📦", data, item['original_filename'], "application/zip", key=item['file_id'])
    else:
        st.caption("아직 작업물이 없어요. 파일을 올려주시면 열심히 정리해드릴게요! 😊")

if __name__ == "__main__":
    main()
