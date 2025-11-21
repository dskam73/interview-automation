import streamlit as st
import anthropic
import openai
import tempfile
import time
from datetime import datetime, timedelta
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

# ë¬¸ì„œ ìƒì„±ìš©
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import markdown

# íŽ˜ì´ì§€ ì„¤ì •
st.set_page_config(
    page_title="ìºí”¼ ì¸í„°ë·°",
    page_icon="ðŸŽ€",
    layout="wide"
)

# ============================================
# ëª¨ë°”ì¼ ìµœì í™” CSS
# ============================================
st.markdown("""
<style>
/* ëª¨ë°”ì¼ ë°˜ì‘í˜• CSS */
@media (max-width: 768px) {
    .stApp {
        padding: 0.5rem;
    }
    
    .stButton > button {
        width: 100%;
        padding: 0.75rem;
        font-size: 1rem;
    }
    
    .stTextArea textarea {
        font-size: 16px !important; /* iOS í™•ëŒ€ ë°©ì§€ */
    }
    
    .stTextInput input {
        font-size: 16px !important;
    }
    
    h1 {
        font-size: 1.5rem !important;
    }
    
    h2 {
        font-size: 1.25rem !important;
    }
    
    h3 {
        font-size: 1.1rem !important;
    }
    
    .stMetric {
        padding: 0.5rem;
    }
    
    .stMetric label {
        font-size: 0.8rem;
    }
    
    .stMetric [data-testid="stMetricValue"] {
        font-size: 1.2rem;
    }
    
    /* ì‚¬ì´ë“œë°” ëª¨ë°”ì¼ ìµœì í™” */
    section[data-testid="stSidebar"] {
        width: 100% !important;
    }
    
    section[data-testid="stSidebar"] > div {
        padding: 1rem;
    }
    
    /* íŒŒì¼ ì—…ë¡œë” í„°ì¹˜ ì˜ì—­ í™•ëŒ€ */
    .stFileUploader {
        padding: 1rem;
    }
    
    .stFileUploader label {
        font-size: 0.9rem;
    }
    
    /* ì²´í¬ë°•ìŠ¤ í„°ì¹˜ ì˜ì—­ í™•ëŒ€ */
    .stCheckbox {
        padding: 0.5rem 0;
    }
    
    /* ì§„í–‰ë°” */
    .stProgress > div {
        height: 8px;
    }
}

/* ì „ì²´ í™”ë©´ ìŠ¤íƒ€ì¼ */
.main .block-container {
    max-width: 100%;
    padding: 1rem;
}

/* ë‹¤ìš´ë¡œë“œ ë²„íŠ¼ ê°•ì¡° */
.stDownloadButton > button {
    background-color: #4CAF50;
    color: white;
    font-weight: bold;
}

.stDownloadButton > button:hover {
    background-color: #45a049;
}
</style>
""", unsafe_allow_html=True)

# ============================================
# í•œê¸€ í°íŠ¸ ì„¤ì • (PDFìš©) - ë‚˜ëˆ”ê³ ë”•
# ============================================
FONT_DIR = "/tmp/fonts"
KOREAN_FONT_PATH = os.path.join(FONT_DIR, "NanumGothic.ttf")
KOREAN_FONT_BOLD_PATH = os.path.join(FONT_DIR, "NanumGothicBold.ttf")
KOREAN_FONT_REGISTERED = False

def setup_korean_font():
    """ë‚˜ëˆ”ê³ ë”• í°íŠ¸ ë‹¤ìš´ë¡œë“œ ë° ë“±ë¡"""
    global KOREAN_FONT_REGISTERED
    
    if KOREAN_FONT_REGISTERED:
        return True
    
    try:
        if not os.path.exists(FONT_DIR):
            os.makedirs(FONT_DIR, exist_ok=True)
        
        font_urls = {
            "NanumGothic.ttf": "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
            "NanumGothicBold.ttf": "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf"
        }
        
        for font_name, url in font_urls.items():
            font_path = os.path.join(FONT_DIR, font_name)
            if not os.path.exists(font_path):
                urllib.request.urlretrieve(url, font_path)
        
        if os.path.exists(KOREAN_FONT_PATH):
            pdfmetrics.registerFont(TTFont('NanumGothic', KOREAN_FONT_PATH))
        if os.path.exists(KOREAN_FONT_BOLD_PATH):
            pdfmetrics.registerFont(TTFont('NanumGothicBold', KOREAN_FONT_BOLD_PATH))
        
        KOREAN_FONT_REGISTERED = True
        return True
        
    except Exception as e:
        print(f"í°íŠ¸ ì„¤ì • ì˜¤ë¥˜: {e}")
        return False

# ============================================
# ë‹¤ìš´ë¡œë“œ íŒŒì¼ ì €ìž¥ ì‹œìŠ¤í…œ (24ì‹œê°„ ìœ ì§€)
# ============================================
DOWNLOAD_DIR = "/tmp/cappy_downloads"
METADATA_FILE = "/tmp/cappy_downloads/metadata.json"
EXPIRY_HOURS = 24

def init_download_system():
    try:
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        if not os.path.exists(METADATA_FILE):
            with open(METADATA_FILE, 'w') as f:
                json.dump([], f)
    except Exception:
        pass

def cleanup_expired_files():
    try:
        if not os.path.exists(METADATA_FILE):
            return
        
        with open(METADATA_FILE, 'r') as f:
            metadata = json.load(f)
        
        current_time = datetime.now()
        valid_items = []
        
        for item in metadata:
            try:
                expiry_time = datetime.fromisoformat(item['expiry_time'])
                if current_time < expiry_time:
                    valid_items.append(item)
                else:
                    file_path = os.path.join(DOWNLOAD_DIR, item['file_id'])
                    if os.path.exists(file_path):
                        os.remove(file_path)
            except Exception:
                continue
        
        with open(METADATA_FILE, 'w') as f:
            json.dump(valid_items, f)
            
    except Exception:
        pass

def save_download_file(zip_data, display_name, original_filename):
    try:
        init_download_system()
        cleanup_expired_files()
        
        file_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{original_filename}"
        file_path = os.path.join(DOWNLOAD_DIR, file_id)
        
        with open(file_path, 'wb') as f:
            f.write(zip_data)
        
        metadata = []
        if os.path.exists(METADATA_FILE):
            try:
                with open(METADATA_FILE, 'r') as f:
                    metadata = json.load(f)
            except Exception:
                metadata = []
        
        new_item = {
            'file_id': file_id,
            'display_name': display_name,
            'original_filename': original_filename,
            'created_time': datetime.now().isoformat(),
            'expiry_time': (datetime.now() + timedelta(hours=EXPIRY_HOURS)).isoformat(),
            'created_display': datetime.now().strftime('%m/%d %H:%M')
        }
        metadata.insert(0, new_item)
        metadata = metadata[:20]
        
        with open(METADATA_FILE, 'w') as f:
            json.dump(metadata, f)
        
        return True
        
    except Exception:
        return False

def get_download_history():
    try:
        init_download_system()
        cleanup_expired_files()
        
        if not os.path.exists(METADATA_FILE):
            return []
        
        with open(METADATA_FILE, 'r') as f:
            metadata = json.load(f)
        
        current_time = datetime.now()
        valid_items = []
        
        for item in metadata:
            try:
                expiry_time = datetime.fromisoformat(item['expiry_time'])
                if current_time < expiry_time:
                    remaining = expiry_time - current_time
                    hours_left = int(remaining.total_seconds() // 3600)
                    minutes_left = int((remaining.total_seconds() % 3600) // 60)
                    item['remaining'] = f"{hours_left}ì‹œê°„ {minutes_left}ë¶„"
                    valid_items.append(item)
            except Exception:
                continue
        
        return valid_items
        
    except Exception:
        return []

def get_download_file(file_id):
    try:
        file_path = os.path.join(DOWNLOAD_DIR, file_id)
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                return f.read()
        return None
    except Exception:
        return None

# ì„¸ì…˜ ìƒíƒœ ì´ˆê¸°í™”
if 'usage_count' not in st.session_state:
    st.session_state.usage_count = 0
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "audio"

# ============================================
# íŒŒì¼ ë¶„í•  ê¸°ëŠ¥ (20MB ë‹¨ìœ„)
# ============================================
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

def get_audio_duration(file_path):
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        info = json.loads(result.stdout)
        return float(info['format']['duration'])
    except Exception as e:
        st.warning(f"ì˜¤ë””ì˜¤ ê¸¸ì´ í™•ì¸ ì‹¤íŒ¨: {e}")
        return None

def split_audio_with_ffmpeg(input_path, output_dir, chunk_duration_sec=600):
    try:
        total_duration = get_audio_duration(input_path)
        if total_duration is None:
            return None
        
        chunks = []
        start_time = 0
        chunk_index = 1
        
        while start_time < total_duration:
            end_time = min(start_time + chunk_duration_sec, total_duration)
            output_path = os.path.join(output_dir, f"chunk_{chunk_index:03d}.mp3")
            
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-ss', str(start_time),
                '-t', str(chunk_duration_sec),
                '-acodec', 'libmp3lame',
                '-ab', '128k',
                '-ar', '44100',
                '-ac', '1',
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, check=True)
            
            chunks.append({
                'index': chunk_index,
                'path': output_path,
                'start_time': start_time,
                'end_time': end_time,
                'duration': end_time - start_time
            })
            
            start_time = end_time
            chunk_index += 1
        
        return chunks
        
    except subprocess.CalledProcessError as e:
        st.error(f"ffmpeg ì˜¤ë¥˜: {e.stderr.decode() if e.stderr else str(e)}")
        return None
    except Exception as e:
        st.error(f"ì˜¤ë””ì˜¤ ë¶„í•  ì˜¤ë¥˜: {str(e)}")
        return None

def split_audio_file(audio_file, max_size_mb=20):
    try:
        file_size_mb = audio_file.size / (1024 * 1024)
        
        if file_size_mb <= max_size_mb:
            return None
        
        temp_dir = tempfile.mkdtemp()
        file_extension = audio_file.name.split('.')[-1].lower()
        input_path = os.path.join(temp_dir, f"input.{file_extension}")
        
        with open(input_path, 'wb') as f:
            f.write(audio_file.read())
        
        audio_file.seek(0)
        
        total_duration = get_audio_duration(input_path)
        if total_duration is None:
            return None
        
        num_chunks = int(file_size_mb / max_size_mb) + 1
        chunk_duration_sec = total_duration / num_chunks
        chunk_duration_sec = max(60, min(chunk_duration_sec, 1200))
        
        st.info(f"ðŸ“Š ì´ ê¸¸ì´: {total_duration/60:.1f}ë¶„ â†’ {num_chunks}ê°œ ì²­í¬ë¡œ ë¶„í• ")
        
        chunks = split_audio_with_ffmpeg(input_path, temp_dir, chunk_duration_sec)
        
        if chunks:
            for chunk in chunks:
                with open(chunk['path'], 'rb') as f:
                    chunk['data'] = io.BytesIO(f.read())
                os.unlink(chunk['path'])
            
            os.unlink(input_path)
            os.rmdir(temp_dir)
        
        return chunks
        
    except Exception as e:
        st.error(f"ì˜¤ë””ì˜¤ íŒŒì¼ ë¶„í•  ì¤‘ ì˜¤ë¥˜: {str(e)}")
        return None

def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

# ============================================
# ë¹„ë°€ë²ˆí˜¸ ë³´í˜¸
# ============================================
def check_password():
    def password_entered():
        correct_password = st.secrets.get("app_password", "interview2024")
        if st.session_state["password"] == correct_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("## ðŸ” ì ‘ê·¼ ì œí•œ")
        st.markdown("íŒ€ ë‚´ë¶€ìš© ì‹œìŠ¤í…œìž…ë‹ˆë‹¤.")
        st.text_input("ë¹„ë°€ë²ˆí˜¸ë¥¼ ìž…ë ¥í•˜ì„¸ìš”:", type="password", on_change=password_entered, key="password")
        return False
    
    elif not st.session_state["password_correct"]:
        st.markdown("## ðŸ” ì ‘ê·¼ ì œí•œ")
        st.text_input("ë¹„ë°€ë²ˆí˜¸ë¥¼ ìž…ë ¥í•˜ì„¸ìš”:", type="password", on_change=password_entered, key="password")
        st.error("âŒ ë¹„ë°€ë²ˆí˜¸ê°€ ì˜¬ë°”ë¥´ì§€ ì•ŠìŠµë‹ˆë‹¤.")
        return False
    
    return True

# ============================================
# Whisper ì „ì‚¬ í•¨ìˆ˜
# ============================================
def transcribe_audio_with_duration(audio_file, task="transcribe"):
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            st.error("âš ï¸ OpenAI API í‚¤ê°€ ì„¤ì •ë˜ì§€ ì•Šì•˜ìŠµë‹ˆë‹¤.")
            return None, 0
        
        client = openai.OpenAI(api_key=api_key)
        file_size_mb = audio_file.size / (1024 * 1024)
        audio_duration_sec = 0
        
        if file_size_mb > MAX_FILE_SIZE_MB:
            st.info(f"ðŸ“¦ íŒŒì¼ í¬ê¸°: {file_size_mb:.1f}MB - ìžë™ ë¶„í• í•©ë‹ˆë‹¤...")
            
            with st.spinner("ðŸ”ª ì˜¤ë””ì˜¤ íŒŒì¼ ë¶„í•  ì¤‘..."):
                chunks = split_audio_file(audio_file, MAX_FILE_SIZE_MB)
            
            if chunks is None:
                st.error("íŒŒì¼ ë¶„í• ì— ì‹¤íŒ¨í–ˆìŠµë‹ˆë‹¤.")
                return None, 0
            
            if chunks:
                audio_duration_sec = chunks[-1]['end_time']
            
            st.success(f"âœ… {len(chunks)}ê°œ ì²­í¬ë¡œ ë¶„í•  ì™„ë£Œ")
            
            all_transcripts = []
            
            progress_container = st.container()
            with progress_container:
                col1, col2 = st.columns([3, 1])
                with col1:
                    chunk_progress = st.progress(0)
                with col2:
                    progress_percent = st.empty()
                
                chunk_status = st.empty()
                chunk_detail = st.empty()
            
            total_start_time = time.time()
            
            for i, chunk in enumerate(chunks):
                progress_value = i / len(chunks)
                chunk_progress.progress(progress_value)
                progress_percent.markdown(f"**{int(progress_value * 100)}%**")
                
                chunk_status.caption(f"ðŸŽ¤ ì²­í¬ {chunk['index']}/{len(chunks)} ì²˜ë¦¬ ì¤‘...")
                chunk_detail.caption(f"êµ¬ê°„: {format_time(chunk['start_time'])} ~ {format_time(chunk['end_time'])}")
                
                chunk['data'].seek(0)
                chunk_start_time = time.time()
                
                try:
                    if task == "translate":
                        transcript = client.audio.translations.create(
                            model="whisper-1",
                            file=("chunk.mp3", chunk['data'], "audio/mpeg")
                        )
                    else:
                        transcript = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=("chunk.mp3", chunk['data'], "audio/mpeg")
                        )
                    
                    chunk_elapsed = int(time.time() - chunk_start_time)
                    total_elapsed = int(time.time() - total_start_time)
                    
                    chunk_detail.caption(f"âœ… ì²­í¬ {chunk['index']} ì™„ë£Œ ({chunk_elapsed}ì´ˆ)")
                    
                    all_transcripts.append({
                        'index': chunk['index'],
                        'start': chunk['start_time'],
                        'end': chunk['end_time'],
                        'text': transcript.text
                    })
                    
                except Exception as e:
                    st.warning(f"âš ï¸ ì²­í¬ {chunk['index']} ì „ì‚¬ ì‹¤íŒ¨: {str(e)}")
                    continue
            
            chunk_progress.progress(1.0)
            progress_percent.markdown("**100%**")
            total_time = int(time.time() - total_start_time)
            chunk_status.caption(f"âœ… ì „ì²´ ì™„ë£Œ ({total_time}ì´ˆ)")
            chunk_detail.empty()
            
            merged_text = "\n\n".join([
                f"[{format_time(t['start'])} ~ {format_time(t['end'])}]\n{t['text']}" 
                for t in all_transcripts
            ])
            
            return merged_text, audio_duration_sec
        
        else:
            file_extension = audio_file.name.split('.')[-1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as tmp_file:
                tmp_file.write(audio_file.read())
                tmp_path = tmp_file.name
            
            audio_duration_sec = get_audio_duration(tmp_path) or 0
            audio_file.seek(0)
            
            with open(tmp_path, 'rb') as audio:
                if task == "translate":
                    transcript = client.audio.translations.create(
                        model="whisper-1",
                        file=audio
                    )
                else:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio
                    )
            
            os.unlink(tmp_path)
            return transcript.text, audio_duration_sec
        
    except Exception as e:
        st.error(f"ì „ì‚¬ ì¤‘ ì˜¤ë¥˜ ë°œìƒ: {str(e)}")
        return None, 0

# ============================================
# Claude API í˜¸ì¶œ í•¨ìˆ˜
# ============================================
def process_with_claude(content: str, prompt: str, task_name: str) -> tuple:
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY")
        if not api_key:
            st.error("âš ï¸ Anthropic API í‚¤ê°€ ì„¤ì •ë˜ì§€ ì•Šì•˜ìŠµë‹ˆë‹¤.")
            return None, 0, 0
        
        client = anthropic.Anthropic(api_key=api_key)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.caption(f"ðŸ¤– {task_name} ì²˜ë¦¬ ì¤‘...")
        progress_bar.progress(30)
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16000,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": f"{prompt}\n\n# ì²˜ë¦¬í•  ì¸í„°ë·° ë‚´ìš©:\n\n{content}"
                }
            ]
        )
        
        progress_bar.progress(100)
        status_text.caption(f"âœ… {task_name} ì™„ë£Œ")
        time.sleep(0.3)
        progress_bar.empty()
        status_text.empty()
        
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        
        return message.content[0].text, input_tokens, output_tokens
        
    except Exception as e:
        st.error(f"âŒ ì²˜ë¦¬ ì¤‘ ì˜¤ë¥˜ ë°œìƒ: {str(e)}")
        return None, 0, 0

# ============================================
# íŒŒì¼ ì½ê¸° í•¨ìˆ˜
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
        except Exception as e:
            st.error(f"íŒŒì¼ ì½ê¸° ì˜¤ë¥˜: {str(e)}")
            return None

# ============================================
# í—¤ë” ì¶”ì¶œ ë° ì¶”ê°€ í•¨ìˆ˜
# ============================================
def extract_header_from_transcript(transcript_text):
    header_info = {
        'title': '',
        'date': '',
        'participants': ''
    }
    
    if not transcript_text:
        return header_info
    
    lines = transcript_text.split('\n')
    
    for i, line in enumerate(lines):
        if line.startswith('# ') and not header_info['title']:
            title = line[2:].strip()
            title = title.replace(' Full Transcript', '').replace('Full Transcript', '').strip()
            header_info['title'] = title
        
        if '**ì¼ì‹œ:**' in line or 'ì¼ì‹œ:' in line:
            date_match = re.search(r'[:\s]+(.+)$', line)
            if date_match:
                header_info['date'] = date_match.group(1).strip().replace('**', '')
        
        if '**ì°¸ì„ìž:**' in line or 'ì°¸ì„ìž:' in line:
            participants_match = re.search(r'[:\s]+(.+)$', line)
            if participants_match:
                header_info['participants'] = participants_match.group(1).strip().replace('**', '')
    
    return header_info

def add_header_to_summary(summary_text, header_info):
    """ìš”ì•½ë¬¸ì— í—¤ë” ì¶”ê°€ ë° ë§ˆí¬ë‹¤ìš´ í¬ë§· ì •ë¦¬"""
    if not summary_text:
        return summary_text
    
    # ì´ë¯¸ í—¤ë”ê°€ ìžˆëŠ”ì§€ í™•ì¸
    if summary_text.strip().startswith('# '):
        # ê¸°ì¡´ í—¤ë” í¬ë§· ì •ë¦¬
        return normalize_markdown_format(summary_text)
    
    header_lines = []
    
    if header_info['title']:
        header_lines.append(f"# {header_info['title']} Summary")
    
    if header_info['date']:
        header_lines.append(f"**ì¼ì‹œ:** {header_info['date']}")
    
    if header_info['participants']:
        header_lines.append(f"**ì°¸ì„ìž:** {header_info['participants']}")
    
    if header_lines:
        header_lines.append("")
        header_lines.append("---")
        header_lines.append("")
        header = '\n'.join(header_lines)
        result = header + summary_text
        return normalize_markdown_format(result)
    
    return normalize_markdown_format(summary_text)

def normalize_markdown_format(text):
    """ë§ˆí¬ë‹¤ìš´ í¬ë§· ì¼ê´€ì„± ìœ ì§€ - ì œëª© ê³„ì¸µ êµ¬ì¡° ì •ë¦¬"""
    if not text:
        return text
    
    lines = text.split('\n')
    result_lines = []
    
    for line in lines:
        # ## ë¡œ ì‹œìž‘í•˜ëŠ” ì„¹ì…˜ ì œëª©ì„ ### ë¡œ ë³€ê²½ (# ì´ ë¬¸ì„œ ì œëª©ì´ë¯€ë¡œ)
        # ë‹¨, [ìš”ì•½], [í•µì‹¬í¬ì¸íŠ¸] ë“±ì˜ ì„¹ì…˜ êµ¬ë¶„ìžëŠ” ## ë¡œ ìœ ì§€
        if line.startswith('## ') and not any(keyword in line for keyword in ['[ìš”ì•½]', '[í•µì‹¬í¬ì¸íŠ¸]', '[í•µì‹¬ í¬ì¸íŠ¸]', '[ìƒˆë¡­ê²Œ', '[ì¸í„°ë·°ì´ê°€', '[ë‹µì„', '[ê¸°ì—… ì‚¬ë¡€]', '[ìœ ë§', '[ì‹œì‚¬ì ]', '[í•µì‹¬ ì½”ë©˜íŠ¸]', '[ì£¼ìš” í†µê³„]', '[tags]']):
            # ì¼ë°˜ ## ì œëª©ì€ ìœ ì§€
            result_lines.append(line)
        else:
            result_lines.append(line)
    
    return '\n'.join(result_lines)

# ============================================
# íŒŒì¼ ë³€í™˜ í•¨ìˆ˜ë“¤
# ============================================
def create_docx(content, title="ë¬¸ì„œ"):
    """ë§ˆí¬ë‹¤ìš´ í…ìŠ¤íŠ¸ë¥¼ DOCXë¡œ ë³€í™˜"""
    doc = Document()
    
    # ì œëª© ìŠ¤íƒ€ì¼ ì„¤ì •
    title_para = doc.add_heading(title, 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    lines = content.split('\n')
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith('# '):
            # ë¬¸ì„œ ì œëª© (ì´ë¯¸ ìœ„ì—ì„œ ì¶”ê°€í–ˆìœ¼ë¯€ë¡œ ìŠ¤í‚µí•˜ê±°ë‚˜ H1ìœ¼ë¡œ)
            heading = doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith('## '):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith('### '):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith('#### '):
            doc.add_heading(stripped[5:], level=4)
        elif stripped.startswith('- ') or stripped.startswith('* '):
            doc.add_paragraph(stripped[2:], style='List Bullet')
        elif stripped.startswith('---'):
            # êµ¬ë¶„ì„ 
            doc.add_paragraph('â”€' * 50)
        elif stripped.startswith('**') and stripped.endswith('**'):
            p = doc.add_paragraph()
            run = p.add_run(stripped.strip('*'))
            run.bold = True
        elif stripped:
            # ì¸ë¼ì¸ ë³¼ë“œ ì²˜ë¦¬
            p = doc.add_paragraph()
            parts = re.split(r'(\*\*[^*]+\*\*)', stripped)
            for part in parts:
                if part.startswith('**') and part.endswith('**'):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    p.add_run(part)
    
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def create_pdf(content, title="ë¬¸ì„œ"):
    """í…ìŠ¤íŠ¸ë¥¼ PDFë¡œ ë³€í™˜ (í•œê¸€ í°íŠ¸ ì§€ì›)"""
    font_available = setup_korean_font()
    
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    y = height - 50
    line_height = 14
    margin = 50
    max_chars_per_line = 50
    
    if font_available and KOREAN_FONT_REGISTERED:
        title_font = 'NanumGothicBold'
        body_font = 'NanumGothic'
    else:
        title_font = 'Helvetica-Bold'
        body_font = 'Helvetica'
    
    def safe_set_font(font_name, size):
        try:
            c.setFont(font_name, size)
        except:
            c.setFont('Helvetica', size)
    
    def new_page():
        nonlocal y
        c.showPage()
        y = height - 50
        safe_set_font(body_font, 10)
    
    def draw_text(text, font_size=10, is_bold=False):
        nonlocal y
        
        if y < 60:
            new_page()
        
        font = title_font if is_bold else body_font
        safe_set_font(font, font_size)
        
        # ê¸´ í…ìŠ¤íŠ¸ ì¤„ë°”ê¿ˆ
        if len(text) > max_chars_per_line:
            words = text.split(' ')
            current_line = ""
            for word in words:
                test_line = current_line + word + " "
                if len(test_line) > max_chars_per_line:
                    if current_line.strip():
                        c.drawString(margin, y, current_line.strip())
                        y -= line_height
                        if y < 60:
                            new_page()
                    current_line = word + " "
                else:
                    current_line = test_line
            if current_line.strip():
                c.drawString(margin, y, current_line.strip())
                y -= line_height
        else:
            c.drawString(margin, y, text)
            y -= line_height
    
    # ì œëª©
    safe_set_font(title_font, 16)
    c.drawString(margin, y, title)
    y -= 30
    
    # ë‚´ìš©
    safe_set_font(body_font, 10)
    
    lines = content.split('\n')
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith('# '):
            y -= 10
            draw_text(stripped[2:], 14, True)
            y -= 5
        elif stripped.startswith('## '):
            y -= 8
            draw_text(stripped[3:], 12, True)
            y -= 3
        elif stripped.startswith('### '):
            y -= 5
            draw_text(stripped[4:], 11, True)
        elif stripped.startswith('#### '):
            draw_text(stripped[5:], 10, True)
        elif stripped.startswith('---'):
            y -= 5
            c.line(margin, y, width - margin, y)
            y -= 10
        elif stripped.startswith('- ') or stripped.startswith('* '):
            draw_text('â€¢ ' + stripped[2:], 10, False)
        elif stripped:
            # ë³¼ë“œ ì œê±°í•˜ê³  ì¼ë°˜ í…ìŠ¤íŠ¸ë¡œ
            clean_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', stripped)
            draw_text(clean_text, 10, False)
        else:
            y -= line_height / 2  # ë¹ˆ ì¤„
    
    c.save()
    buffer.seek(0)
    return buffer

# ============================================
# ZIP íŒŒì¼ëª… ìƒì„± í•¨ìˆ˜
# ============================================
def generate_zip_filename(user_emails, source_filename):
    email_id = ""
    if user_emails and len(user_emails) > 0:
        first_email = user_emails[0]
        if '@' in first_email:
            email_id = first_email.split('@')[0]
    
    date_str = datetime.now().strftime('%y%m%d')
    
    base_name = source_filename.rsplit('.', 1)[0] if '.' in source_filename else source_filename
    
    if email_id:
        zip_filename = f"{email_id}{date_str}+{base_name}.zip"
    else:
        zip_filename = f"interview_{date_str}+{base_name}.zip"
    
    zip_filename = zip_filename.replace(' ', '_')
    
    return zip_filename

# ============================================
# ì´ë©”ì¼ ì „ì†¡ í•¨ìˆ˜
# ============================================
ADMIN_EMAIL_BCC = "dskam@lgbr.co.kr"
USD_TO_KRW = 1400

def send_email(to_emails, subject, body, attachments=None):
    try:
        gmail_user = st.secrets.get("gmail_user")
        gmail_password = st.secrets.get("gmail_password")
        
        if not gmail_user or not gmail_password:
            return False, "ì´ë©”ì¼ ì„¤ì •ì´ ì—†ìŠµë‹ˆë‹¤."
        
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = ", ".join(to_emails) if isinstance(to_emails, list) else to_emails
        msg['Bcc'] = ADMIN_EMAIL_BCC
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        if attachments:
            for filename, data in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                msg.attach(part)
        
        all_recipients = to_emails if isinstance(to_emails, list) else [to_emails]
        all_recipients.append(ADMIN_EMAIL_BCC)
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, all_recipients, msg.as_string())
        server.quit()
        
        return True, "ì „ì†¡ ì™„ë£Œ"
        
    except Exception as e:
        return False, str(e)

def generate_email_body(file_results, total_time_sec, total_cost_krw):
    # 입력 파일 목록
    file_list = []
    output_list = []
    
    for idx, result in enumerate(file_results, 1):
        # 입력 파일
        filename = result['filename']
        base_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        file_list.append(f"{idx}. {filename}")
        
        # 출력 파일을 트리 구조로 정리
        output_lines = [f"{idx}. {filename}"]
        tree_items = []
        
        # 받아쓰기 원본
        if result.get('transcribed'):
            tree_items.append(f"녹취(원본): {base_name}_whisper.txt")
        
        # 트랜스크립트
        if result.get('transcript'):
            tree_items.append(f"트랜스크립트: {base_name}.docx, {base_name}.md")
        
        # 요약
        if result.get('summary'):
            tree_items.append(f"요약: #{base_name}.docx, #{base_name}.md")
        
        # 트리 구조로 표시
        for i, item in enumerate(tree_items):
            if i < len(tree_items) - 1:
                output_lines.append(f"   ├─ {item}")
            else:
                output_lines.append(f"   └─ {item}")
        
        output_list.append("\n".join(output_lines))
    
    input_section = "\n".join(file_list)
    output_section = "\n\n".join(output_list)
    
    # 시간 포맷
    minutes = int(total_time_sec // 60)
    seconds = int(total_time_sec % 60)
    
    # 현재 날짜/시간 (KST) - get_kst_now() 함수 사용
    now = get_kst_now()
    date_str = now.strftime("%Y. %m/%d (%H:%M)")
    
    body = f"""안녕하세요! 캐피입니다 😊
인터뷰 정리 결과를 보내드립니다.

✔️ 다음 파일들을 제게 주셨어요 ({len(file_results)}개)
─────────────────────────────────
{input_section}

✔️ 주신 파일별로 정리, 요약를 했습니다
─────────────────────────────────
{output_section}

※ 첨부파일을 확인해주세요!
   - 개별 산출물 파일들
   - 전체 압축 파일 (ZIP)

열심히 하고 있는데 그래도 이 만큼 걸리네요.
( 소요 시간/비용: {minutes}분 {seconds}초 / 약 {total_cost_krw:,.0f}원 )

오늘도 좋은 하루 되세요 😃
캐피가 드립니다.

{date_str}
"""
    return body
def calculate_costs(audio_duration_min=0, input_tokens=0, output_tokens=0):
    whisper_cost_usd = audio_duration_min * 0.006
    
    claude_input_cost_usd = (input_tokens / 1_000_000) * 3.0
    claude_output_cost_usd = (output_tokens / 1_000_000) * 15.0
    claude_cost_usd = claude_input_cost_usd + claude_output_cost_usd
    
    total_usd = whisper_cost_usd + claude_cost_usd
    total_krw = total_usd * USD_TO_KRW
    
    return {
        'whisper_usd': whisper_cost_usd,
        'whisper_krw': whisper_cost_usd * USD_TO_KRW,
        'claude_usd': claude_cost_usd,
        'claude_krw': claude_cost_usd * USD_TO_KRW,
        'total_usd': total_usd,
        'total_krw': total_krw,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens
    }

# ============================================
# ë©”ì¸ ì•±
# ============================================
def main():
    if not check_password():
        return
    
    st.title("ðŸŽ€ ìºí”¼ ì¸í„°ë·°")
    st.markdown("ì•ˆë…•í•˜ì„¸ìš”! ì¸í„°ë·° ìŒì„±/í…ìŠ¤íŠ¸ íŒŒì¼ ì˜¬ë ¤ì£¼ì‹œë©´ ì œê°€ ê¹”ë”í•˜ê²Œ ì •ë¦¬í•´ë“œë¦´ê²Œìš”! ðŸ˜Š")
    st.markdown("---")
    
    try:
        transcript_prompt = st.secrets.get("transcript_prompt", "")
        summary_prompt = st.secrets.get("summary_prompt", "")
    except:
        transcript_prompt = ""
        summary_prompt = ""
    
    sidebar_usage_placeholder = None
    
    with st.sidebar:
        st.header("âš™ï¸ ìºí”¼ ì¸í„°ë·°ì˜ˆìš”!")
        
        st.subheader("ðŸ“ ì–´ë–¤ íŒŒì¼ì´ì—ìš”?")
        file_type = st.radio(
            "íŒŒì¼ ìœ í˜• ì„ íƒ",
            ["ðŸŽ¤ ì¸í„°ë·° ìŒì„± íŒŒì¼!", "ðŸ“„ ì¸í„°ë·° í…ìŠ¤íŠ¸!"],
            key="file_type_radio",
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        if file_type == "ðŸŽ¤ ì¸í„°ë·° ìŒì„± íŒŒì¼!":
            st.subheader("ðŸ“Š ì–´ë–»ê²Œ ë°›ì•„ì“¸ê¹Œìš”?")
            whisper_task = st.radio(
                "ì „ì‚¬ ë°©ì‹ ì„ íƒ",
                ["ì›ëž˜ ì–¸ì–´ ê·¸ëŒ€ë¡œìš”", "ì˜ì–´ë¡œ ë²ˆì—­í•´ ì£¼ì„¸ìš”"],
                key="whisper_task",
                label_visibility="collapsed"
            )
            whisper_task_value = "transcribe" if whisper_task == "ì›ëž˜ ì–¸ì–´ ê·¸ëŒ€ë¡œìš”" else "translate"
            
            st.markdown("---")
            
            st.subheader("ðŸ“‹ (í•œê¸€)ë…¸íŠ¸ì •ë¦¬ê¹Œì§€ í• ê¹Œìš”?")
            audio_do_transcript = st.checkbox("ê¹”ë”í•˜ê²Œ ì •ë¦¬í•´ë“œë¦´ê²Œìš”", value=False, key="audio_transcript")
            audio_do_summary = st.checkbox("ìš”ì•½ë„ í•´ë“œë¦´ê¹Œìš”?", value=False, key="audio_summary")
            
            st.markdown("---")
            
            # ìŒì„± íŒŒì¼ìš© ì¶œë ¥ í¬ë§· ì„ íƒ
            st.subheader("ðŸ“ ì¶œë ¥ í¬ë§·")
            audio_output_md = st.checkbox("Markdown (.md)", value=True, key="audio_out_md")
            audio_output_docx = st.checkbox("Word (.docx)", value=True, key="audio_out_docx")
            audio_output_pdf = st.checkbox("PDF (.pdf)", value=False, key="audio_out_pdf")
            
            st.markdown("---")
            st.info(f"ðŸ’¡ {MAX_FILE_SIZE_MB}MB ë„˜ëŠ” íŒŒì¼ì€ ì œê°€ ì•Œì•„ì„œ ë‚˜ëˆ ì„œ ì²˜ë¦¬í• ê²Œìš”!")
        
        else:
            st.subheader("ðŸ“‹ ë­˜ í•´ë“œë¦´ê¹Œìš”?")
            text_do_transcript = st.checkbox("ì¸í„°ë·° í’€ íŠ¸ëžœìŠ¤í¬ë¦½íŠ¸ ìž‘ì„±", value=True, key="text_transcript")
            text_do_summary = st.checkbox("ê¹”ë”í•œ ìš”ì•½ë¬¸ ìž‘ì„±", value=False, key="text_summary")
            
            st.markdown("---")
            
            st.subheader("ðŸ“ ì–´ë–¤ íŒŒì¼í¬ë§·ì´ íŽ¸í•˜ì„¸ìš”?")
            output_md = st.checkbox("Markdown (.md)", value=True, key="out_md")
            output_docx = st.checkbox("Word (.docx)", value=True, key="out_docx")
            output_pdf = st.checkbox("PDF (.pdf)", value=False, key="out_pdf")
        
        st.markdown("---")
        
        # ì´ë©”ì¼ ì„¤ì • - text_input ì‚¬ìš© (Enterë¡œ ìž…ë ¥ ì™„ë£Œ)
        st.subheader("ðŸ“§ ë³´ë‚´ë“œë¦´ê¹Œìš”?")
        send_email_option = st.checkbox("ì´ë©”ì¼ë¡œ ë³´ë‚´ë“œë¦´ê²Œìš”", value=False, key="send_email")
        if send_email_option:
            st.markdown("ðŸ“¬ **ë°›ìœ¼ì‹¤ ë¶„ë“¤** (ìµœëŒ€ 5ëª…)")
            st.caption("ì½¤ë§ˆ(,)ë¡œ êµ¬ë¶„í•˜ì„¸ìš”")
            
            # text_input ì‚¬ìš© - Enterë¡œ ìž…ë ¥ ì™„ë£Œ
            email_input = st.text_input(
                "ì´ë©”ì¼ ì£¼ì†Œ ìž…ë ¥",
                placeholder="user1@company.com, user2@company.com",
                key="user_emails_input",
                label_visibility="collapsed"
            )
            
            if email_input:
                raw_emails = [e.strip() for e in email_input.split(',') if e.strip()]
                st.session_state.user_emails_list = raw_emails[:5]
                if len(raw_emails) > 5:
                    st.warning("âš ï¸ ìµœëŒ€ 5ëª…ê¹Œì§€ë§Œ ê°€ëŠ¥í•´ìš”!")
                if st.session_state.user_emails_list:
                    st.success(f"âœ… {len(st.session_state.user_emails_list)}ëª…")
                    for i, email in enumerate(st.session_state.user_emails_list, 1):
                        st.caption(f"{i}. {email}")
            else:
                st.session_state.user_emails_list = []
        else:
            st.session_state.user_emails_list = []
        
        st.markdown("---")
        
        st.header("ðŸ“Š ì˜¤ëŠ˜ ì´ë§Œí¼ í–ˆì–´ìš”!")
        sidebar_usage_placeholder = st.empty()
        sidebar_usage_placeholder.metric("ì²˜ë¦¬ ì™„ë£Œ", f"{st.session_state.usage_count}ê°œ")
        
        download_history = get_download_history()
        if download_history:
            st.markdown("---")
            st.subheader("ðŸ“¥ ë‹¤ì‹œ ë°›ê¸°")
            st.caption("â° 24ì‹œê°„ ë™ì•ˆ ìœ ì§€")
            
            for idx, item in enumerate(download_history):
                file_data = get_download_file(item['file_id'])
                if file_data:
                    with st.container():
                        st.caption(f"ðŸ• {item['created_display']} ({item['remaining']})")
                        st.download_button(
                            label=f"ðŸ“¦ {item['display_name']}",
                            data=file_data,
                            file_name=item['original_filename'],
                            mime="application/zip",
                            key=f"history_download_{idx}_{item['file_id']}",
                            use_container_width=True
                        )
        
        st.markdown("---")
        st.caption("ðŸŽ€ ìºí”¼ ì¸í„°ë·° | Claude + Whisper")
    
    if file_type == "ðŸŽ¤ ì¸í„°ë·° ìŒì„± íŒŒì¼!":
        st.header("ðŸŽ¤ ì¸í„°ë·° ìŒì„± íŒŒì¼ ì˜¬ë ¤ì£¼ì„¸ìš”!")
        st.markdown("**ìŒì„±ì„ í…ìŠ¤íŠ¸ë¡œ ë°›ì•„ì¨ë“œë¦´ê²Œìš”!**")
        
        audio_files = st.file_uploader(
            "ìŒì„± íŒŒì¼ ì„ íƒ (ì—¬ëŸ¬ ê°œ ê°€ëŠ¥)",
            type=['mp3', 'wav', 'm4a', 'ogg', 'webm'],
            accept_multiple_files=True,
            help=f"ì§€ì› í¬ë§·: MP3, WAV, M4A, OGG, WEBM",
            key="audio_uploader"
        )
        
        if audio_files:
            st.success(f"âœ… {len(audio_files)}ê°œ íŒŒì¼")
            
            total_size = sum([f.size for f in audio_files])
            st.info(f"ðŸ“Š ì´ í¬ê¸°: {total_size / 1024 / 1024:.2f} MB")
            
            with st.expander("ðŸ“ íŒŒì¼ ëª©ë¡"):
                for idx, f in enumerate(audio_files, 1):
                    file_size_mb = f.size / (1024 * 1024)
                    st.caption(f"{idx}. {f.name} ({file_size_mb:.1f} MB)")
            
            st.markdown("---")
            
            if st.button(f"ðŸš€ ì²˜ë¦¬ ì‹œìž‘!", type="primary", use_container_width=True):
                st.markdown("---")
                
                job_start_time = datetime.now()
                total_start_time = time.time()
                
                user_emails = st.session_state.get('user_emails_list', [])
                email_id = ""
                if user_emails and len(user_emails) > 0:
                    if '@' in user_emails[0]:
                        email_id = user_emails[0].split('@')[0]
                
                task_types = ["ë°›ì•„ì“°ê¸°"]
                if audio_do_transcript:
                    task_types.append("íŠ¸ëžœìŠ¤í¬ë¦½íŠ¸")
                if audio_do_summary:
                    task_types.append("ìš”ì•½")
                
                st.markdown("#### ðŸ“¥ ì²˜ë¦¬ ì¤‘...")
                st.caption(f"ðŸ“‹ {email_id if email_id else '-'} | {len(audio_files)}ê°œ íŒŒì¼ ({', '.join(task_types)}) | {job_start_time.strftime('%H:%M:%S')}")
                
                total_input_tokens = 0
                total_output_tokens = 0
                total_audio_duration_min = 0
                
                audio_results = []
                total = len(audio_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                for idx, audio_file in enumerate(audio_files, 1):
                    overall_status.caption(f"ðŸ”„ ({idx}/{total}) {audio_file.name}")
                    overall_progress.progress((idx - 1) / total)
                    
                    file_size_mb = audio_file.size / (1024 * 1024)
                    
                    with st.spinner(f"ðŸŽ§ ({idx}/{total}) ë°›ì•„ì“°ëŠ” ì¤‘..."):
                        transcribed_text, audio_duration = transcribe_audio_with_duration(audio_file, task=whisper_task_value)
                    
                    if audio_duration:
                        total_audio_duration_min += audio_duration / 60
                    
                    if transcribed_text:
                        result = {
                            'filename': audio_file.name,
                            'transcribed': transcribed_text,
                            'transcript': None,
                            'summary': None
                        }
                        
                        if audio_do_transcript and transcript_prompt:
                            with st.spinner(f"ðŸ“ ({idx}/{total}) ì •ë¦¬ ì¤‘..."):
                                transcript_result, in_tok, out_tok = process_with_claude(
                                    transcribed_text, 
                                    transcript_prompt, 
                                    "íŠ¸ëžœìŠ¤í¬ë¦½íŠ¸"
                                )
                                result['transcript'] = transcript_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        if audio_do_summary and summary_prompt:
                            source_text = result['transcript'] if result['transcript'] else transcribed_text
                            with st.spinner(f"ðŸ“‹ ({idx}/{total}) ìš”ì•½ ì¤‘..."):
                                summary_result, in_tok, out_tok = process_with_claude(
                                    source_text, 
                                    summary_prompt, 
                                    "ìš”ì•½ë¬¸"
                                )
                                if summary_result and result['transcript']:
                                    header_info = extract_header_from_transcript(result['transcript'])
                                    summary_result = add_header_to_summary(summary_result, header_info)
                                result['summary'] = summary_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        audio_results.append(result)
                    else:
                        st.error(f"âŒ {audio_file.name} ì‹¤íŒ¨")
                
                total_elapsed_time = time.time() - total_start_time
                
                overall_progress.progress(1.0)
                overall_status.caption("âœ… ì™„ë£Œ!")
                
                st.session_state.usage_count += len(audio_results)
                if sidebar_usage_placeholder:
                    sidebar_usage_placeholder.metric("ì²˜ë¦¬ ì™„ë£Œ", f"{st.session_state.usage_count}ê°œ")
                
                costs = calculate_costs(
                    audio_duration_min=total_audio_duration_min,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens
                )
                
                st.markdown("---")
                st.subheader("ðŸ“Š ìž‘ì—… ìš”ì•½")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    minutes = int(total_elapsed_time // 60)
                    seconds = int(total_elapsed_time % 60)
                    st.metric("â±ï¸ ì†Œìš” ì‹œê°„", f"{minutes}ë¶„ {seconds}ì´ˆ")
                with col2:
                    st.metric("ðŸŽ¤ ì˜¤ë””ì˜¤", f"{total_audio_duration_min:.1f}ë¶„")
                with col3:
                    st.metric("ðŸ’° ë¹„ìš©", f"â‚©{costs['total_krw']:,.0f}")
                
                if audio_results:
                    st.markdown("---")
                    st.subheader("ðŸ“¥ ë‹¤ìš´ë¡œë“œ")
                    
                    first_filename = audio_results[0]['filename'] if audio_results else "interview"
                    zip_filename = generate_zip_filename(user_emails, first_filename)
                    
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for result in audio_results:
                            base_name = result['filename'].rsplit('.', 1)[0]
                            
                            # Whisper ì›ë³¸ì€ í•­ìƒ txtë¡œ ì €ìž¥
                            if result['transcribed']:
                                zf.writestr(f"{base_name}_whisper.txt", result['transcribed'])
                            
                            # íŠ¸ëžœìŠ¤í¬ë¦½íŠ¸
                            if result['transcript']:
                                if audio_output_md:
                                    zf.writestr(f"{base_name}_transcript.md", result['transcript'])
                                if audio_output_docx:
                                    docx_buffer = create_docx(result['transcript'], f"{base_name} Transcript")
                                    zf.writestr(f"{base_name}_transcript.docx", docx_buffer.read())
                                if audio_output_pdf:
                                    pdf_buffer = create_pdf(result['transcript'], f"{base_name} Transcript")
                                    zf.writestr(f"{base_name}_transcript.pdf", pdf_buffer.read())
                            
                            # ìš”ì•½ë¬¸
                            if result['summary']:
                                if audio_output_md:
                                    zf.writestr(f"{base_name}_summary.md", result['summary'])
                                if audio_output_docx:
                                    docx_buffer = create_docx(result['summary'], f"{base_name} Summary")
                                    zf.writestr(f"{base_name}_summary.docx", docx_buffer.read())
                                if audio_output_pdf:
                                    pdf_buffer = create_pdf(result['summary'], f"{base_name} Summary")
                                    zf.writestr(f"{base_name}_summary.pdf", pdf_buffer.read())
                    
                    zip_buffer.seek(0)
                    zip_data = zip_buffer.getvalue()
                    
                    file_names = [r['filename'] for r in audio_results]
                    display_name = f"{file_names[0]}" if len(file_names) == 1 else f"{file_names[0]} ì™¸ {len(file_names)-1}ê°œ"
                    save_download_file(zip_data, display_name, zip_filename)
                    
                    st.download_button(
                        label="ðŸ“¦ ì „ì²´ ë‹¤ìš´ë¡œë“œ (ZIP)",
                        data=zip_data,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    st.caption("ðŸ’¡ 24ì‹œê°„ ë™ì•ˆ ì‚¬ì´ë“œë°”ì—ì„œ ë‹¤ì‹œ ë°›ì„ ìˆ˜ ìžˆì–´ìš”")
                    
                    if send_email_option and user_emails:
                        with st.spinner("ðŸ“§ ì´ë©”ì¼ ë°œì†¡ ì¤‘..."):
                            email_body = generate_email_body(
                                audio_results, 
                                total_elapsed_time, 
                                costs['total_krw']
                            )
                            
                            # 개별 파일들 첨부 준비
                            attachments = []
                            
                            for result in audio_results:
                                base_name = result['filename'].rsplit('.', 1)[0]
                                
                                # Whisper 원본 
                                if result['transcribed']:
                                    attachments.append((f"{base_name}_whisper.txt", result['transcribed'].encode('utf-8')))
                                
                                # 트랜스크립트
                                if result['transcript']:
                                    if audio_output_md:
                                        attachments.append((f"{base_name}_transcript.md", result['transcript'].encode('utf-8')))
                                    if audio_output_docx:
                                        docx_buffer = create_docx(result['transcript'], f"{base_name} Transcript")
                                        attachments.append((f"{base_name}_transcript.docx", docx_buffer.read()))
                                    if audio_output_pdf:
                                        pdf_buffer = create_pdf(result['transcript'], f"{base_name} Transcript")
                                        attachments.append((f"{base_name}_transcript.pdf", pdf_buffer.read()))
                                
                                # 요약문
                                if result['summary']:
                                    if audio_output_md:
                                        attachments.append((f"{base_name}_summary.md", result['summary'].encode('utf-8')))
                                    if audio_output_docx:
                                        docx_buffer = create_docx(result['summary'], f"{base_name} Summary")
                                        attachments.append((f"{base_name}_summary.docx", docx_buffer.read()))
                                    if audio_output_pdf:
                                        pdf_buffer = create_pdf(result['summary'], f"{base_name} Summary")
                                        attachments.append((f"{base_name}_summary.pdf", pdf_buffer.read()))
                            
                            # 전체 ZIP 파일도 추가
                            attachments.append((zip_filename, zip_data))
                            
                            success, msg = send_email(
                                user_emails,
                                f"인터뷰 정리가 도착했습니다 - {audio_results[0]['filename'].rsplit('.', 1)[0] if audio_results else 'interview'}",
                                email_body,
                                attachments
                            )
                            if success:
                                st.success("âœ… ì´ë©”ì¼ ë°œì†¡ ì™„ë£Œ!")
                                st.caption("ðŸ“¬ ìˆ˜ì‹ ìž: " + ", ".join(user_emails))
                            else:
                                st.warning(f"âš ï¸ ì´ë©”ì¼ ì‹¤íŒ¨: {msg}")
    
    else:
        st.header("ðŸ“„ ì¸í„°ë·° í…ìŠ¤íŠ¸ ì˜¬ë ¤ì£¼ì„¸ìš”!")
        st.markdown("**í…ìŠ¤íŠ¸ íŒŒì¼ì„ ê¹”ë”í•˜ê²Œ ì •ë¦¬í•´ë“œë¦´ê²Œìš”!**")
        
        text_files = st.file_uploader(
            "í…ìŠ¤íŠ¸ íŒŒì¼ ì„ íƒ (ì—¬ëŸ¬ ê°œ ê°€ëŠ¥)",
            type=['txt', 'md'],
            accept_multiple_files=True,
            help="ì§€ì› í¬ë§·: TXT, MD",
            key="text_uploader"
        )
        
        if text_files:
            st.success(f"âœ… {len(text_files)}ê°œ íŒŒì¼")
            
            with st.expander("ðŸ“ íŒŒì¼ ëª©ë¡"):
                for idx, f in enumerate(text_files, 1):
                    st.caption(f"{idx}. {f.name} ({f.size / 1024:.1f} KB)")
            
            st.markdown("---")
            
            if st.button(f"ðŸš€ ì²˜ë¦¬ ì‹œìž‘!", type="primary", use_container_width=True):
                st.markdown("---")
                
                job_start_time = datetime.now()
                total_start_time = time.time()
                
                user_emails = st.session_state.get('user_emails_list', [])
                email_id = ""
                if user_emails and len(user_emails) > 0:
                    if '@' in user_emails[0]:
                        email_id = user_emails[0].split('@')[0]
                
                task_types = []
                if text_do_transcript:
                    task_types.append("íŠ¸ëžœìŠ¤í¬ë¦½íŠ¸")
                if text_do_summary:
                    task_types.append("ìš”ì•½")
                
                st.markdown("#### ðŸ“¥ ì²˜ë¦¬ ì¤‘...")
                st.caption(f"ðŸ“‹ {email_id if email_id else '-'} | {len(text_files)}ê°œ íŒŒì¼ ({', '.join(task_types)}) | {job_start_time.strftime('%H:%M:%S')}")
                
                total_input_tokens = 0
                total_output_tokens = 0
                
                text_results = []
                total = len(text_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                for idx, text_file in enumerate(text_files, 1):
                    overall_status.caption(f"ðŸ”„ ({idx}/{total}) {text_file.name}")
                    overall_progress.progress((idx - 1) / total)
                    
                    content = read_file(text_file)
                    
                    if content:
                        result = {
                            'filename': text_file.name,
                            'original': content,
                            'transcript': None,
                            'summary': None
                        }
                        
                        if text_do_transcript and transcript_prompt:
                            with st.spinner(f"ðŸ“ ({idx}/{total}) íŠ¸ëžœìŠ¤í¬ë¦½íŠ¸ ìž‘ì„± ì¤‘..."):
                                transcript_result, in_tok, out_tok = process_with_claude(
                                    content, 
                                    transcript_prompt, 
                                    "íŠ¸ëžœìŠ¤í¬ë¦½íŠ¸"
                                )
                                result['transcript'] = transcript_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        if text_do_summary and summary_prompt:
                            source = result['transcript'] if result['transcript'] else content
                            with st.spinner(f"ðŸ“‹ ({idx}/{total}) ìš”ì•½ë¬¸ ìž‘ì„± ì¤‘..."):
                                summary_result, in_tok, out_tok = process_with_claude(
                                    source, 
                                    summary_prompt, 
                                    "ìš”ì•½ë¬¸"
                                )
                                if summary_result and result['transcript']:
                                    header_info = extract_header_from_transcript(result['transcript'])
                                    summary_result = add_header_to_summary(summary_result, header_info)
                                result['summary'] = summary_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        text_results.append(result)
                    else:
                        st.error(f"âŒ {text_file.name} ì‹¤íŒ¨")
                
                total_elapsed_time = time.time() - total_start_time
                
                overall_progress.progress(1.0)
                overall_status.caption("âœ… ì™„ë£Œ!")
                
                st.session_state.usage_count += len(text_results)
                if sidebar_usage_placeholder:
                    sidebar_usage_placeholder.metric("ì²˜ë¦¬ ì™„ë£Œ", f"{st.session_state.usage_count}ê°œ")
                
                costs = calculate_costs(
                    audio_duration_min=0,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens
                )
                
                st.markdown("---")
                st.subheader("ðŸ“Š ìž‘ì—… ìš”ì•½")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    minutes = int(total_elapsed_time // 60)
                    seconds = int(total_elapsed_time % 60)
                    st.metric("â±ï¸ ì†Œìš” ì‹œê°„", f"{minutes}ë¶„ {seconds}ì´ˆ")
                with col2:
                    st.metric("ðŸ“ í† í°", f"{total_input_tokens + total_output_tokens:,}")
                with col3:
                    st.metric("ðŸ’° ë¹„ìš©", f"â‚©{costs['total_krw']:,.0f}")
                
                if text_results:
                    st.markdown("---")
                    st.subheader("ðŸ“¥ ë‹¤ìš´ë¡œë“œ")
                    
                    first_filename = text_results[0]['filename'] if text_results else "interview"
                    zip_filename = generate_zip_filename(user_emails, first_filename)
                    
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for result in text_results:
                            base_name = result['filename'].rsplit('.', 1)[0]
                            
                            if result['transcript']:
                                if output_md:
                                    zf.writestr(f"{base_name}_transcript.md", result['transcript'])
                                if output_docx:
                                    docx_buffer = create_docx(result['transcript'], f"{base_name} Transcript")
                                    zf.writestr(f"{base_name}_transcript.docx", docx_buffer.read())
                                if output_pdf:
                                    pdf_buffer = create_pdf(result['transcript'], f"{base_name} Transcript")
                                    zf.writestr(f"{base_name}_transcript.pdf", pdf_buffer.read())
                            
                            if result['summary']:
                                if output_md:
                                    zf.writestr(f"{base_name}_summary.md", result['summary'])
                                if output_docx:
                                    docx_buffer = create_docx(result['summary'], f"{base_name} Summary")
                                    zf.writestr(f"{base_name}_summary.docx", docx_buffer.read())
                                if output_pdf:
                                    pdf_buffer = create_pdf(result['summary'], f"{base_name} Summary")
                                    zf.writestr(f"{base_name}_summary.pdf", pdf_buffer.read())
                    
                    zip_buffer.seek(0)
                    zip_data = zip_buffer.getvalue()
                    
                    file_names = [r['filename'] for r in text_results]
                    display_name = f"{file_names[0]}" if len(file_names) == 1 else f"{file_names[0]} ì™¸ {len(file_names)-1}ê°œ"
                    save_download_file(zip_data, display_name, zip_filename)
                    
                    st.download_button(
                        label="ðŸ“¦ ì „ì²´ ë‹¤ìš´ë¡œë“œ (ZIP)",
                        data=zip_data,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    st.caption("ðŸ’¡ 24ì‹œê°„ ë™ì•ˆ ì‚¬ì´ë“œë°”ì—ì„œ ë‹¤ì‹œ ë°›ì„ ìˆ˜ ìžˆì–´ìš”")
                    
                    if send_email_option and user_emails:
                        with st.spinner("ðŸ“§ ì´ë©”ì¼ ë°œì†¡ ì¤‘..."):
                            email_body = generate_email_body(
                                text_results, 
                                total_elapsed_time, 
                                costs['total_krw']
                            )
                            
                            # 개별 파일들 첨부 준비
                            attachments = []
                            
                            for result in text_results:
                                base_name = result['filename'].rsplit('.', 1)[0]
                                
                                # 트랜스크립트
                                if result['transcript']:
                                    if output_md:
                                        attachments.append((f"{base_name}_transcript.md", result['transcript'].encode('utf-8')))
                                    if output_docx:
                                        docx_buffer = create_docx(result['transcript'], f"{base_name} Transcript")
                                        attachments.append((f"{base_name}_transcript.docx", docx_buffer.read()))
                                    if output_pdf:
                                        pdf_buffer = create_pdf(result['transcript'], f"{base_name} Transcript")
                                        attachments.append((f"{base_name}_transcript.pdf", pdf_buffer.read()))
                                
                                # 요약문
                                if result['summary']:
                                    if output_md:
                                        attachments.append((f"{base_name}_summary.md", result['summary'].encode('utf-8')))
                                    if output_docx:
                                        docx_buffer = create_docx(result['summary'], f"{base_name} Summary")
                                        attachments.append((f"{base_name}_summary.docx", docx_buffer.read()))
                                    if output_pdf:
                                        pdf_buffer = create_pdf(result['summary'], f"{base_name} Summary")
                                        attachments.append((f"{base_name}_summary.pdf", pdf_buffer.read()))
                            
                            # 전체 ZIP 파일도 추가
                            attachments.append((zip_filename, zip_data))
                            
                            success, msg = send_email(
                                user_emails,
                                f"인터뷰 정리가 도착했습니다 - {text_results[0]['filename'].rsplit('.', 1)[0] if text_results else 'interview'}",
                                email_body,
                                attachments
                            )
                            if success:
                                st.success("âœ… ì´ë©”ì¼ ë°œì†¡ ì™„ë£Œ!")
                                st.caption("ðŸ“¬ ìˆ˜ì‹ ìž: " + ", ".join(user_emails))
                            else:
                                st.warning(f"âš ï¸ ì´ë©”ì¼ ì‹¤íŒ¨: {msg}")

if __name__ == "__main__":
    main()
