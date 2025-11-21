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
import markdown

# 페이지 설정
st.set_page_config(
    page_title="캐피 인터뷰",
    page_icon="🎀",
    layout="wide"
)

# ============================================
# 한국 표준시 (KST) 설정
# ============================================
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """한국 표준시 현재 시간 반환"""
    return datetime.now(KST)

# ============================================
# 모바일 최적화 CSS
# ============================================
st.markdown("""
<style>
/* 모바일 반응형 CSS */
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
        font-size: 16px !important; /* iOS 확대 방지 */
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
    
    /* 사이드바 모바일 최적화 */
    section[data-testid="stSidebar"] {
        width: 100% !important;
    }
    
    section[data-testid="stSidebar"] > div {
        padding: 1rem;
    }
    
    /* 파일 업로더 터치 영역 확대 */
    .stFileUploader {
        padding: 1rem;
    }
    
    .stFileUploader label {
        font-size: 0.9rem;
    }
    
    /* 체크박스 터치 영역 확대 */
    .stCheckbox {
        padding: 0.5rem 0;
    }
    
    /* 진행바 */
    .stProgress > div {
        height: 8px;
    }
}

/* 전체 화면 스타일 */
.main .block-container {
    max-width: 100%;
    padding: 1rem;
}

/* 다운로드 버튼 강조 */
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
# 한글 폰트 설정 (DOCX용) - 나눔고딕
# ============================================
FONT_DIR = "/tmp/fonts"
KOREAN_FONT_PATH = os.path.join(FONT_DIR, "NanumGothic.ttf")
KOREAN_FONT_BOLD_PATH = os.path.join(FONT_DIR, "NanumGothicBold.ttf")
KOREAN_FONT_REGISTERED = False

def setup_korean_font():
    """나눔고딕 폰트 다운로드 및 등록"""
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
        
        KOREAN_FONT_REGISTERED = True
        return True
        
    except Exception as e:
        print(f"폰트 설정 오류: {e}")
        return False

# ============================================
# 사용량 제한 설정
# ============================================
MAX_FILES_PER_UPLOAD = 5  # 한 번에 최대 업로드 가능 파일 수
DAILY_LIMIT_AUDIO = 30    # 하루 최대 음성 파일 처리 수 (앱 전체 기준)
DAILY_LIMIT_TEXT = 30     # 하루 최대 텍스트 파일 처리 수 (앱 전체 기준)
USAGE_FILE = "/tmp/cappy_usage.json"

def init_usage_system():
    """사용량 추적 시스템 초기화"""
    try:
        if not os.path.exists(USAGE_FILE):
            reset_daily_usage()
    except Exception:
        pass

def get_daily_usage():
    """오늘의 사용량 조회"""
    try:
        init_usage_system()
        
        if not os.path.exists(USAGE_FILE):
            return {'audio': 0, 'text': 0, 'date': get_kst_now().strftime('%Y-%m-%d')}
        
        with open(USAGE_FILE, 'r') as f:
            usage = json.load(f)
        
        # 날짜가 바뀌었으면 리셋
        today = get_kst_now().strftime('%Y-%m-%d')
        if usage.get('date') != today:
            reset_daily_usage()
            return {'audio': 0, 'text': 0, 'date': today}
        
        return usage
        
    except Exception:
        return {'audio': 0, 'text': 0, 'date': get_kst_now().strftime('%Y-%m-%d')}

def reset_daily_usage():
    """일일 사용량 리셋"""
    try:
        today = get_kst_now().strftime('%Y-%m-%d')
        usage = {'audio': 0, 'text': 0, 'date': today}
        with open(USAGE_FILE, 'w') as f:
            json.dump(usage, f)
        return usage
    except Exception:
        return {'audio': 0, 'text': 0, 'date': get_kst_now().strftime('%Y-%m-%d')}

def update_usage(file_type, count):
    """사용량 업데이트 (file_type: 'audio' 또는 'text')"""
    try:
        usage = get_daily_usage()
        usage[file_type] = usage.get(file_type, 0) + count
        with open(USAGE_FILE, 'w') as f:
            json.dump(usage, f)
        return usage
    except Exception:
        return None

def check_usage_limit(file_type, requested_count):
    """사용량 한도 체크 - 처리 가능 여부와 남은 한도 반환"""
    usage = get_daily_usage()
    current = usage.get(file_type, 0)
    limit = DAILY_LIMIT_AUDIO if file_type == 'audio' else DAILY_LIMIT_TEXT
    remaining = limit - current
    
    return {
        'can_process': remaining > 0,
        'current': current,
        'limit': limit,
        'remaining': remaining,
        'requested': requested_count,
        'allowed': min(requested_count, remaining)
    }

# ============================================
# 다운로드 파일 저장 시스템 (24시간 유지)
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
        
        current_time = get_kst_now()
        valid_items = []
        
        for item in metadata:
            try:
                expiry_time = datetime.fromisoformat(item['expiry_time'])
                if expiry_time.tzinfo is None:
                    expiry_time = expiry_time.replace(tzinfo=KST)
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
            except Exception:
                metadata = []
        
        new_item = {
            'file_id': file_id,
            'display_name': display_name,
            'original_filename': original_filename,
            'created_time': now.isoformat(),
            'expiry_time': (now + timedelta(hours=EXPIRY_HOURS)).isoformat(),
            'created_display': now.strftime('%m/%d %H:%M')
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
        
        current_time = get_kst_now()
        valid_items = []
        
        for item in metadata:
            try:
                expiry_time = datetime.fromisoformat(item['expiry_time'])
                if expiry_time.tzinfo is None:
                    expiry_time = expiry_time.replace(tzinfo=KST)
                if current_time < expiry_time:
                    remaining = expiry_time - current_time
                    hours_left = int(remaining.total_seconds() // 3600)
                    minutes_left = int((remaining.total_seconds() % 3600) // 60)
                    item['remaining'] = f"{hours_left}시간 {minutes_left}분"
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

# 세션 상태 초기화
if 'usage_count' not in st.session_state:
    st.session_state.usage_count = 0
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "audio"

# ============================================
# 파일 분할 기능 (20MB 단위)
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
        st.warning(f"오디오 길이 확인 실패: {e}")
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
        st.error(f"ffmpeg 오류: {e.stderr.decode() if e.stderr else str(e)}")
        return None
    except Exception as e:
        st.error(f"오디오 분할 오류: {str(e)}")
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
        
        st.info(f"📊 총 길이: {total_duration/60:.1f}분 → {num_chunks}개 청크로 분할")
        
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
        st.error(f"오디오 파일 분할 중 오류: {str(e)}")
        return None

def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

# ============================================
# 비밀번호 보호
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
        st.markdown("## 🔐 접근 제한")
        st.markdown("팀 내부용 시스템입니다.")
        st.text_input("비밀번호를 입력하세요:", type="password", on_change=password_entered, key="password")
        return False
    
    elif not st.session_state["password_correct"]:
        st.markdown("## 🔐 접근 제한")
        st.text_input("비밀번호를 입력하세요:", type="password", on_change=password_entered, key="password")
        st.error("❌ 비밀번호가 올바르지 않습니다.")
        return False
    
    return True

# ============================================
# Whisper 전사 함수
# ============================================
def transcribe_audio_with_duration(audio_file, task="transcribe"):
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            st.error("⚠️ OpenAI API 키가 설정되지 않았습니다.")
            return None, 0
        
        client = openai.OpenAI(api_key=api_key)
        file_size_mb = audio_file.size / (1024 * 1024)
        audio_duration_sec = 0
        
        if file_size_mb > MAX_FILE_SIZE_MB:
            st.info(f"📦 파일 크기: {file_size_mb:.1f}MB - 자동 분할합니다...")
            
            with st.spinner("🔪 오디오 파일 분할 중..."):
                chunks = split_audio_file(audio_file, MAX_FILE_SIZE_MB)
            
            if chunks is None:
                st.error("파일 분할에 실패했습니다.")
                return None, 0
            
            if chunks:
                audio_duration_sec = chunks[-1]['end_time']
            
            st.success(f"✅ {len(chunks)}개 청크로 분할 완료")
            
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
                
                chunk_status.caption(f"🎤 청크 {chunk['index']}/{len(chunks)} 처리 중...")
                chunk_detail.caption(f"구간: {format_time(chunk['start_time'])} ~ {format_time(chunk['end_time'])}")
                
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
                    
                    chunk_detail.caption(f"✅ 청크 {chunk['index']} 완료 ({chunk_elapsed}초)")
                    
                    all_transcripts.append({
                        'index': chunk['index'],
                        'start': chunk['start_time'],
                        'end': chunk['end_time'],
                        'text': transcript.text
                    })
                    
                except Exception as e:
                    st.warning(f"⚠️ 청크 {chunk['index']} 전사 실패: {str(e)}")
                    continue
            
            chunk_progress.progress(1.0)
            progress_percent.markdown("**100%**")
            total_time = int(time.time() - total_start_time)
            chunk_status.caption(f"✅ 전체 완료 ({total_time}초)")
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
        st.error(f"전사 중 오류 발생: {str(e)}")
        return None, 0

# ============================================
# Claude API 호출 함수
# ============================================
def process_with_claude(content: str, prompt: str, task_name: str) -> tuple:
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY")
        if not api_key:
            st.error("⚠️ Anthropic API 키가 설정되지 않았습니다.")
            return None, 0, 0
        
        client = anthropic.Anthropic(api_key=api_key)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.caption(f"🤖 {task_name} 처리 중...")
        progress_bar.progress(30)
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16000,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": f"{prompt}\n\n# 처리할 인터뷰 내용:\n\n{content}"
                }
            ]
        )
        
        progress_bar.progress(100)
        status_text.caption(f"✅ {task_name} 완료")
        time.sleep(0.3)
        progress_bar.empty()
        status_text.empty()
        
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        
        return message.content[0].text, input_tokens, output_tokens
        
    except Exception as e:
        st.error(f"❌ 처리 중 오류 발생: {str(e)}")
        return None, 0, 0

# ============================================
# 파일 읽기 함수
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
            st.error(f"파일 읽기 오류: {str(e)}")
            return None

# ============================================
# 헤더 추출 및 추가 함수
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
        
        if '**일시:**' in line or '일시:' in line:
            date_match = re.search(r'[:\s]+(.+)$', line)
            if date_match:
                header_info['date'] = date_match.group(1).strip().replace('**', '')
        
        if '**참석자:**' in line or '참석자:' in line:
            participants_match = re.search(r'[:\s]+(.+)$', line)
            if participants_match:
                header_info['participants'] = participants_match.group(1).strip().replace('**', '')
    
    return header_info

def add_header_to_summary(summary_text, header_info):
    """요약문에 헤더 추가 및 마크다운 포맷 정리"""
    if not summary_text:
        return summary_text
    
    # 이미 헤더가 있는지 확인
    if summary_text.strip().startswith('# '):
        # 기존 헤더 포맷 정리
        return normalize_markdown_format(summary_text)
    
    header_lines = []
    
    if header_info['title']:
        header_lines.append(f"# {header_info['title']} Summary")
    
    if header_info['date']:
        header_lines.append(f"**일시:** {header_info['date']}")
    
    if header_info['participants']:
        header_lines.append(f"**참석자:** {header_info['participants']}")
    
    if header_lines:
        header_lines.append("")
        header_lines.append("---")
        header_lines.append("")
        header = '\n'.join(header_lines)
        result = header + summary_text
        return normalize_markdown_format(result)
    
    return normalize_markdown_format(summary_text)

def normalize_markdown_format(text):
    """마크다운 포맷 일관성 유지 - 요약문의 모든 소제목을 ### (lv3)로 통일"""
    if not text:
        return text
    
    lines = text.split('\n')
    result_lines = []
    
    # 섹션 구분자 키워드 (## 레벨 유지)
    section_keywords = ['[요약]', '[핵심포인트]', '[핵심 포인트]', '[새롭게', '[인터뷰이가', 
                       '[답을', '[기업 사례]', '[유망', '[시사점]', '[핵심 코멘트]', 
                       '[주요 통계]', '[tags]']
    
    for line in lines:
        # # 으로 시작하는 문서 제목은 유지
        if line.startswith('# ') and not line.startswith('## '):
            result_lines.append(line)
        # ## 로 시작하는 경우
        elif line.startswith('## '):
            # 섹션 구분자 키워드가 포함된 경우 ## 유지
            if any(keyword in line for keyword in section_keywords):
                result_lines.append(line)
            else:
                # 그 외의 ## 제목은 ### 로 변경
                result_lines.append('###' + line[2:])
        # ### 이상은 그대로 유지
        else:
            result_lines.append(line)
    
    return '\n'.join(result_lines)

# ============================================
# 파일 변환 함수들
# ============================================
DOCX_FONT_NAME = 'LG스마트체 Regular'

def set_docx_font(run, font_name=DOCX_FONT_NAME, font_size=11):
    """DOCX Run에 폰트 설정"""
    run.font.name = font_name
    run.font.size = Pt(font_size)
    # 한글 폰트 설정을 위한 추가 설정
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn('w:eastAsia'), font_name)

def create_docx(content, title="문서"):
    """마크다운 텍스트를 DOCX로 변환 (LG스마트체 폰트 적용)"""
    doc = Document()
    
    # 기본 스타일 설정
    style = doc.styles['Normal']
    style.font.name = DOCX_FONT_NAME
    style.font.size = Pt(11)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), DOCX_FONT_NAME)
    
    # 제목 스타일 설정
    title_para = doc.add_heading(title, 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title_para.runs:
        set_docx_font(run, DOCX_FONT_NAME, 18)
    
    lines = content.split('\n')
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith('# '):
            heading = doc.add_heading(stripped[2:], level=1)
            for run in heading.runs:
                set_docx_font(run, DOCX_FONT_NAME, 16)
        elif stripped.startswith('## '):
            heading = doc.add_heading(stripped[3:], level=2)
            for run in heading.runs:
                set_docx_font(run, DOCX_FONT_NAME, 14)
        elif stripped.startswith('### '):
            heading = doc.add_heading(stripped[4:], level=3)
            for run in heading.runs:
                set_docx_font(run, DOCX_FONT_NAME, 12)
        elif stripped.startswith('#### '):
            heading = doc.add_heading(stripped[5:], level=4)
            for run in heading.runs:
                set_docx_font(run, DOCX_FONT_NAME, 11)
        elif stripped.startswith('- ') or stripped.startswith('* '):
            p = doc.add_paragraph(stripped[2:], style='List Bullet')
            for run in p.runs:
                set_docx_font(run, DOCX_FONT_NAME, 11)
        elif stripped.startswith('---'):
            # 구분선
            p = doc.add_paragraph('─' * 50)
            for run in p.runs:
                set_docx_font(run, DOCX_FONT_NAME, 11)
        elif stripped.startswith('**') and stripped.endswith('**'):
            p = doc.add_paragraph()
            run = p.add_run(stripped.strip('*'))
            run.bold = True
            set_docx_font(run, DOCX_FONT_NAME, 11)
        elif stripped:
            # 인라인 볼드 처리
            p = doc.add_paragraph()
            parts = re.split(r'(\*\*[^*]+\*\*)', stripped)
            for part in parts:
                if part.startswith('**') and part.endswith('**'):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                    set_docx_font(run, DOCX_FONT_NAME, 11)
                else:
                    run = p.add_run(part)
                    set_docx_font(run, DOCX_FONT_NAME, 11)
    
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# ============================================
# ZIP 파일명 생성 함수
# ============================================
def generate_zip_filename(user_emails, source_filename):
    email_id = ""
    if user_emails and len(user_emails) > 0:
        first_email = user_emails[0]
        if '@' in first_email:
            email_id = first_email.split('@')[0]
    
    date_str = get_kst_now().strftime('%y%m%d')
    
    base_name = source_filename.rsplit('.', 1)[0] if '.' in source_filename else source_filename
    
    if email_id:
        zip_filename = f"{email_id}{date_str}+{base_name}.zip"
    else:
        zip_filename = f"interview_{date_str}+{base_name}.zip"
    
    zip_filename = zip_filename.replace(' ', '_')
    
    return zip_filename

# ============================================
# 이메일 전송 함수
# ============================================
ADMIN_EMAIL_BCC = "dskam@lgbr.co.kr"
USD_TO_KRW = 1400

def send_email(to_emails, subject, body, attachments=None):
    try:
        gmail_user = st.secrets.get("gmail_user")
        gmail_password = st.secrets.get("gmail_password")
        
        if not gmail_user or not gmail_password:
            return False, "이메일 설정이 없습니다."
        
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
        
        return True, "전송 완료"
        
    except Exception as e:
        return False, str(e)

def generate_email_body(file_results, total_time_sec, total_cost_krw):
    file_list = ""
    for result in file_results:
        tasks = []
        if result.get('transcribed'):
            tasks.append("받아쓰기")
        if result.get('transcript'):
            tasks.append("트랜스크립트")
        if result.get('summary'):
            tasks.append("요약문")
        
        task_str = ", ".join(tasks) if tasks else "처리완료"
        file_list += f"• {result['filename']}: {task_str}\n"
    
    minutes = int(total_time_sec // 60)
    seconds = int(total_time_sec % 60)
    time_str = f"{minutes}분 {seconds}초" if minutes > 0 else f"{seconds}초"
    
    body = f"""안녕하세요! 부문 막내, 캐피입니다😊
부탁하신 인터뷰 정리 결과를 공유드립니다.

1. 처리 내용
{file_list}
2. 처리 시간/비용
• 처리시간: {time_str}
• 처리비용: 약 {total_cost_krw:,.0f}원

첨부파일을 확인해주세요! 문의사항 있으시면 편하게 말씀해주세요. 감사합니다! 🙇‍♀️

───────────────────────────────────────
🎀 캐피 인터뷰(@사업1)
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
# 메인 앱
# ============================================
def main():
    if not check_password():
        return
    
    st.title("🎀 캐피 인터뷰")
    
    try:
        transcript_prompt = st.secrets.get("transcript_prompt", "")
        summary_prompt = st.secrets.get("summary_prompt", "")
    except:
        transcript_prompt = ""
        summary_prompt = ""
    
    sidebar_usage_placeholder = None
    
    with st.sidebar:
        st.header("⚙️ 설정")
        
        file_type = st.radio(
            "파일 유형",
            ["🎤 인터뷰 음성 파일!", "📄 인터뷰 텍스트!"],
            key="file_type_radio",
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        if file_type == "🎤 인터뷰 음성 파일!":
            st.subheader("📊 어떻게 받아쓸까요?")
            whisper_task = st.radio(
                "전사 방식 선택",
                ["원래 언어 그대로요", "영어로 번역해 주세요"],
                key="whisper_task",
                label_visibility="collapsed"
            )
            whisper_task_value = "transcribe" if whisper_task == "원래 언어 그대로요" else "translate"
            
            st.markdown("---")
            
            st.subheader("📋 (한글)노트정리까지 할까요?")
            audio_do_transcript = st.checkbox("깔끔하게 정리해드릴게요", value=False, key="audio_transcript")
            audio_do_summary = st.checkbox("요약도 해드릴까요?", value=False, key="audio_summary")
            
            st.markdown("---")
            
            # 음성 파일용 출력 포맷 선택 (PDF 제거, txt 추가)
            st.subheader("📝 출력 포맷")
            audio_output_md = st.checkbox("Markdown (.md)", value=True, key="audio_out_md")
            audio_output_docx = st.checkbox("Word (.docx)", value=True, key="audio_out_docx")
            audio_output_txt = st.checkbox("Text (.txt)", value=True, key="audio_out_txt")
            
            st.markdown("---")
            st.info(f"💡 {MAX_FILE_SIZE_MB}MB 넘는 파일은 제가 알아서 나눠서 처리할게요!")
        
        else:
            st.subheader("📋 뭘 해드릴까요?")
            text_do_transcript = st.checkbox("인터뷰 풀 트랜스크립트 작성", value=True, key="text_transcript")
            text_do_summary = st.checkbox("깔끔한 요약문 작성", value=False, key="text_summary")
            
            st.markdown("---")
            
            # 텍스트 파일용 출력 포맷 선택 (PDF 제거, txt 추가)
            st.subheader("📝 어떤 파일포맷이 편하세요?")
            output_md = st.checkbox("Markdown (.md)", value=True, key="out_md")
            output_docx = st.checkbox("Word (.docx)", value=True, key="out_docx")
            output_txt = st.checkbox("Text (.txt)", value=True, key="out_txt")
        
        st.markdown("---")
        
        # 이메일 설정 - text_input 사용 (Enter로 입력 완료)
        st.subheader("📧 보내드릴까요?")
        send_email_option = st.checkbox("이메일로 보내드릴게요", value=False, key="send_email")
        if send_email_option:
            st.markdown("📬 **받으실 분들** (최대 5명)")
            st.caption("콤마(,)로 구분하세요")
            
            # text_input 사용 - Enter로 입력 완료
            email_input = st.text_input(
                "이메일 주소 입력",
                placeholder="user1@company.com, user2@company.com",
                key="user_emails_input",
                label_visibility="collapsed"
            )
            
            if email_input:
                raw_emails = [e.strip() for e in email_input.split(',') if e.strip()]
                st.session_state.user_emails_list = raw_emails[:5]
                if len(raw_emails) > 5:
                    st.warning("⚠️ 최대 5명까지만 가능해요!")
                if st.session_state.user_emails_list:
                    st.success(f"✅ {len(st.session_state.user_emails_list)}명")
                    for i, email in enumerate(st.session_state.user_emails_list, 1):
                        st.caption(f"{i}. {email}")
            else:
                st.session_state.user_emails_list = []
        else:
            st.session_state.user_emails_list = []
        
        st.markdown("---")
        
        st.header("📊 오늘 사용량")
        
        # 일일 사용량 표시
        daily_usage = get_daily_usage()
        col_audio, col_text = st.columns(2)
        with col_audio:
            audio_remaining = DAILY_LIMIT_AUDIO - daily_usage.get('audio', 0)
            st.metric("🎤 음성", f"{daily_usage.get('audio', 0)}/{DAILY_LIMIT_AUDIO}", 
                     delta=f"남음: {audio_remaining}", delta_color="normal")
        with col_text:
            text_remaining = DAILY_LIMIT_TEXT - daily_usage.get('text', 0)
            st.metric("📄 텍스트", f"{daily_usage.get('text', 0)}/{DAILY_LIMIT_TEXT}",
                     delta=f"남음: {text_remaining}", delta_color="normal")
        
        st.caption(f"📅 기준일: {daily_usage.get('date', '-')}")
        
        sidebar_usage_placeholder = st.empty()
        sidebar_usage_placeholder.metric("이번 세션 처리", f"{st.session_state.usage_count}개")
        
        download_history = get_download_history()
        if download_history:
            st.markdown("---")
            st.subheader("📥 다시 받기")
            st.caption("⏰ 24시간 동안 유지")
            
            for idx, item in enumerate(download_history):
                file_data = get_download_file(item['file_id'])
                if file_data:
                    with st.container():
                        st.caption(f"🕐 {item['created_display']} ({item['remaining']})")
                        st.download_button(
                            label=f"📦 {item['display_name']}",
                            data=file_data,
                            file_name=item['original_filename'],
                            mime="application/zip",
                            key=f"history_download_{idx}_{item['file_id']}",
                            use_container_width=True
                        )
        
        st.markdown("---")
        st.caption("🎀 캐피 인터뷰 | Claude + Whisper")
    
    if file_type == "🎤 인터뷰 음성 파일!":
        st.subheader("🎤 음성 파일 업로드")
        
        # 사용량 체크
        audio_usage = check_usage_limit('audio', MAX_FILES_PER_UPLOAD)
        
        if not audio_usage['can_process']:
            st.error(f"⚠️ 오늘 처리 한도({DAILY_LIMIT_AUDIO}개)에 도달했어요. 내일 이용해주세요!")
        else:
            audio_files = st.file_uploader(
                f"파일 선택 (최대 {MAX_FILES_PER_UPLOAD}개, 남은 한도: {audio_usage['remaining']}개)",
                type=['mp3', 'wav', 'm4a', 'ogg', 'webm'],
                accept_multiple_files=True,
                key="audio_uploader"
            )
            
            if audio_files:
                # 업로드 개수 제한 체크
                if len(audio_files) > MAX_FILES_PER_UPLOAD:
                    st.warning(f"⚠️ 최대 {MAX_FILES_PER_UPLOAD}개만 처리됩니다.")
                    audio_files = audio_files[:MAX_FILES_PER_UPLOAD]
                
                # 일일 한도 체크
                usage_check = check_usage_limit('audio', len(audio_files))
                if len(audio_files) > usage_check['remaining']:
                    st.warning(f"⚠️ 오늘은 {usage_check['remaining']}개만 처리됩니다.")
                    audio_files = audio_files[:usage_check['remaining']]
                
                if len(audio_files) > 0:
                    total_size = sum([f.size for f in audio_files])
                    st.caption(f"✅ {len(audio_files)}개 파일 · {total_size / 1024 / 1024:.1f} MB")
                    
                    # 파일 목록은 2개 이상일 때만 표시
                    if len(audio_files) > 1:
                        with st.expander("📁 파일 목록"):
                            for idx, f in enumerate(audio_files, 1):
                                st.caption(f"{idx}. {f.name} ({f.size / 1024 / 1024:.1f} MB)")
                    
                    st.markdown("---")
            
            if st.button(f"🚀 처리 시작!", type="primary", use_container_width=True):
                st.markdown("---")
                
                job_start_time = get_kst_now()
                total_start_time = time.time()
                
                user_emails = st.session_state.get('user_emails_list', [])
                email_id = ""
                if user_emails and len(user_emails) > 0:
                    if '@' in user_emails[0]:
                        email_id = user_emails[0].split('@')[0]
                
                task_types = ["받아쓰기"]
                if audio_do_transcript:
                    task_types.append("트랜스크립트")
                if audio_do_summary:
                    task_types.append("요약")
                
                st.markdown("#### 📥 처리 중...")
                st.caption(f"📋 {email_id if email_id else '-'} | {len(audio_files)}개 파일 ({', '.join(task_types)}) | {job_start_time.strftime('%H:%M:%S')} KST")
                
                total_input_tokens = 0
                total_output_tokens = 0
                total_audio_duration_min = 0
                
                audio_results = []
                total = len(audio_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                for idx, audio_file in enumerate(audio_files, 1):
                    overall_status.caption(f"📄 ({idx}/{total}) {audio_file.name}")
                    overall_progress.progress((idx - 1) / total)
                    
                    file_size_mb = audio_file.size / (1024 * 1024)
                    
                    with st.spinner(f"🎧 ({idx}/{total}) 받아쓰는 중..."):
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
                            with st.spinner(f"📝 ({idx}/{total}) 정리 중..."):
                                transcript_result, in_tok, out_tok = process_with_claude(
                                    transcribed_text, 
                                    transcript_prompt, 
                                    "트랜스크립트"
                                )
                                result['transcript'] = transcript_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        if audio_do_summary and summary_prompt:
                            source_text = result['transcript'] if result['transcript'] else transcribed_text
                            with st.spinner(f"📋 ({idx}/{total}) 요약 중..."):
                                summary_result, in_tok, out_tok = process_with_claude(
                                    source_text, 
                                    summary_prompt, 
                                    "요약문"
                                )
                                if summary_result and result['transcript']:
                                    header_info = extract_header_from_transcript(result['transcript'])
                                    summary_result = add_header_to_summary(summary_result, header_info)
                                result['summary'] = summary_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        audio_results.append(result)
                    else:
                        st.error(f"❌ {audio_file.name} 실패")
                
                total_elapsed_time = time.time() - total_start_time
                
                overall_progress.progress(1.0)
                overall_status.caption("✅ 완료!")
                
                # 세션 사용량 업데이트
                st.session_state.usage_count += len(audio_results)
                if sidebar_usage_placeholder:
                    sidebar_usage_placeholder.metric("이번 세션 처리", f"{st.session_state.usage_count}개")
                
                # 일일 사용량 업데이트
                if len(audio_results) > 0:
                    update_usage('audio', len(audio_results))
                
                costs = calculate_costs(
                    audio_duration_min=total_audio_duration_min,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens
                )
                
                st.markdown("---")
                st.subheader("📊 작업 요약")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    minutes = int(total_elapsed_time // 60)
                    seconds = int(total_elapsed_time % 60)
                    st.metric("⏱️ 소요 시간", f"{minutes}분 {seconds}초")
                with col2:
                    st.metric("🎤 오디오", f"{total_audio_duration_min:.1f}분")
                with col3:
                    st.metric("💰 비용", f"₩{costs['total_krw']:,.0f}")
                
                if audio_results:
                    st.markdown("---")
                    st.subheader("📥 다운로드")
                    
                    first_filename = audio_results[0]['filename'] if audio_results else "interview"
                    zip_filename = generate_zip_filename(user_emails, first_filename)
                    
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for result in audio_results:
                            base_name = result['filename'].rsplit('.', 1)[0]
                            
                            # Whisper 원본은 항상 txt로 저장
                            if result['transcribed']:
                                zf.writestr(f"{base_name}_whisper.txt", result['transcribed'])
                            
                            # 트랜스크립트 - 원본 파일명 그대로 사용
                            if result['transcript']:
                                if audio_output_md:
                                    zf.writestr(f"{base_name}.md", result['transcript'])
                                if audio_output_docx:
                                    docx_buffer = create_docx(result['transcript'], base_name)
                                    zf.writestr(f"{base_name}.docx", docx_buffer.read())
                                if audio_output_txt:
                                    plain_text = re.sub(r'[#*_\-]+', '', result['transcript'])
                                    plain_text = re.sub(r'\n{3,}', '\n\n', plain_text)
                                    zf.writestr(f"{base_name}.txt", plain_text)
                            
                            # 요약문 - 파일명 앞에 # 붙임
                            if result['summary']:
                                if audio_output_md:
                                    zf.writestr(f"#{base_name}.md", result['summary'])
                                if audio_output_docx:
                                    docx_buffer = create_docx(result['summary'], f"#{base_name}")
                                    zf.writestr(f"#{base_name}.docx", docx_buffer.read())
                                if audio_output_txt:
                                    plain_text = re.sub(r'[#*_\-]+', '', result['summary'])
                                    plain_text = re.sub(r'\n{3,}', '\n\n', plain_text)
                                    zf.writestr(f"#{base_name}.txt", plain_text)
                    
                    zip_buffer.seek(0)
                    zip_data = zip_buffer.getvalue()
                    
                    file_names = [r['filename'] for r in audio_results]
                    display_name = f"{file_names[0]}" if len(file_names) == 1 else f"{file_names[0]} 외 {len(file_names)-1}개"
                    save_download_file(zip_data, display_name, zip_filename)
                    
                    st.download_button(
                        label="📦 전체 다운로드 (ZIP)",
                        data=zip_data,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    st.caption("💡 24시간 동안 사이드바에서 다시 받을 수 있어요")
                    
                    if send_email_option and user_emails:
                        with st.spinner("📧 이메일 발송 중..."):
                            email_body = generate_email_body(
                                audio_results, 
                                total_elapsed_time, 
                                costs['total_krw']
                            )
                            
                            attachments = [(zip_filename, zip_data)]
                            success, msg = send_email(
                                user_emails,
                                f"[캐피 인터뷰] 인터뷰 정리 결과 - {get_kst_now().strftime('%Y-%m-%d')}",
                                email_body,
                                attachments
                            )
                            if success:
                                st.success("✅ 이메일 발송 완료!")
                                st.caption("📬 수신자: " + ", ".join(user_emails))
                            else:
                                st.warning(f"⚠️ 이메일 실패: {msg}")
    
    else:
        st.subheader("📄 텍스트 파일 업로드")
        
        # 사용량 체크
        text_usage = check_usage_limit('text', MAX_FILES_PER_UPLOAD)
        
        if not text_usage['can_process']:
            st.error(f"⚠️ 오늘 처리 한도({DAILY_LIMIT_TEXT}개)에 도달했어요. 내일 이용해주세요!")
        else:
            text_files = st.file_uploader(
                f"파일 선택 (최대 {MAX_FILES_PER_UPLOAD}개, 남은 한도: {text_usage['remaining']}개)",
                type=['txt', 'md'],
                accept_multiple_files=True,
                key="text_uploader"
            )
            
            if text_files:
                # 업로드 개수 제한 체크
                if len(text_files) > MAX_FILES_PER_UPLOAD:
                    st.warning(f"⚠️ 최대 {MAX_FILES_PER_UPLOAD}개만 처리됩니다.")
                    text_files = text_files[:MAX_FILES_PER_UPLOAD]
                
                # 일일 한도 체크
                usage_check = check_usage_limit('text', len(text_files))
                if len(text_files) > usage_check['remaining']:
                    st.warning(f"⚠️ 오늘은 {usage_check['remaining']}개만 처리됩니다.")
                    text_files = text_files[:usage_check['remaining']]
                
                if len(text_files) > 0:
                    total_size = sum([f.size for f in text_files])
                    st.caption(f"✅ {len(text_files)}개 파일 · {total_size / 1024:.1f} KB")
                    
                    # 파일 목록은 2개 이상일 때만 표시
                    if len(text_files) > 1:
                        with st.expander("📁 파일 목록"):
                            for idx, f in enumerate(text_files, 1):
                                st.caption(f"{idx}. {f.name} ({f.size / 1024:.1f} KB)")
                    
                    st.markdown("---")
                    
                    if st.button(f"🚀 처리 시작!", type="primary", use_container_width=True, key="text_process_btn"):
                        st.markdown("---")
                
                job_start_time = get_kst_now()
                total_start_time = time.time()
                
                user_emails = st.session_state.get('user_emails_list', [])
                email_id = ""
                if user_emails and len(user_emails) > 0:
                    if '@' in user_emails[0]:
                        email_id = user_emails[0].split('@')[0]
                
                task_types = []
                if text_do_transcript:
                    task_types.append("트랜스크립트")
                if text_do_summary:
                    task_types.append("요약")
                
                st.markdown("#### 📥 처리 중...")
                st.caption(f"📋 {email_id if email_id else '-'} | {len(text_files)}개 파일 ({', '.join(task_types)}) | {job_start_time.strftime('%H:%M:%S')} KST")
                
                total_input_tokens = 0
                total_output_tokens = 0
                
                text_results = []
                total = len(text_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                for idx, text_file in enumerate(text_files, 1):
                    overall_status.caption(f"📄 ({idx}/{total}) {text_file.name}")
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
                            with st.spinner(f"📝 ({idx}/{total}) 트랜스크립트 작성 중..."):
                                transcript_result, in_tok, out_tok = process_with_claude(
                                    content, 
                                    transcript_prompt, 
                                    "트랜스크립트"
                                )
                                result['transcript'] = transcript_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        if text_do_summary and summary_prompt:
                            source = result['transcript'] if result['transcript'] else content
                            with st.spinner(f"📋 ({idx}/{total}) 요약문 작성 중..."):
                                summary_result, in_tok, out_tok = process_with_claude(
                                    source, 
                                    summary_prompt, 
                                    "요약문"
                                )
                                if summary_result and result['transcript']:
                                    header_info = extract_header_from_transcript(result['transcript'])
                                    summary_result = add_header_to_summary(summary_result, header_info)
                                result['summary'] = summary_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        text_results.append(result)
                    else:
                        st.error(f"❌ {text_file.name} 실패")
                
                total_elapsed_time = time.time() - total_start_time
                
                overall_progress.progress(1.0)
                overall_status.caption("✅ 완료!")
                
                # 세션 사용량 업데이트
                st.session_state.usage_count += len(text_results)
                if sidebar_usage_placeholder:
                    sidebar_usage_placeholder.metric("이번 세션 처리", f"{st.session_state.usage_count}개")
                
                # 일일 사용량 업데이트
                if len(text_results) > 0:
                    update_usage('text', len(text_results))
                
                costs = calculate_costs(
                    audio_duration_min=0,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens
                )
                
                st.markdown("---")
                st.subheader("📊 작업 요약")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    minutes = int(total_elapsed_time // 60)
                    seconds = int(total_elapsed_time % 60)
                    st.metric("⏱️ 소요 시간", f"{minutes}분 {seconds}초")
                with col2:
                    st.metric("📝 토큰", f"{total_input_tokens + total_output_tokens:,}")
                with col3:
                    st.metric("💰 비용", f"₩{costs['total_krw']:,.0f}")
                
                if text_results:
                    st.markdown("---")
                    st.subheader("📥 다운로드")
                    
                    first_filename = text_results[0]['filename'] if text_results else "interview"
                    zip_filename = generate_zip_filename(user_emails, first_filename)
                    
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for result in text_results:
                            base_name = result['filename'].rsplit('.', 1)[0]
                            
                            # 트랜스크립트 - 원본 파일명 그대로 사용
                            if result['transcript']:
                                if output_md:
                                    zf.writestr(f"{base_name}.md", result['transcript'])
                                if output_docx:
                                    docx_buffer = create_docx(result['transcript'], base_name)
                                    zf.writestr(f"{base_name}.docx", docx_buffer.read())
                                if output_txt:
                                    plain_text = re.sub(r'[#*_\-]+', '', result['transcript'])
                                    plain_text = re.sub(r'\n{3,}', '\n\n', plain_text)
                                    zf.writestr(f"{base_name}.txt", plain_text)
                            
                            # 요약문 - 파일명 앞에 # 붙임
                            if result['summary']:
                                if output_md:
                                    zf.writestr(f"#{base_name}.md", result['summary'])
                                if output_docx:
                                    docx_buffer = create_docx(result['summary'], f"#{base_name}")
                                    zf.writestr(f"#{base_name}.docx", docx_buffer.read())
                                if output_txt:
                                    plain_text = re.sub(r'[#*_\-]+', '', result['summary'])
                                    plain_text = re.sub(r'\n{3,}', '\n\n', plain_text)
                                    zf.writestr(f"#{base_name}.txt", plain_text)
                    
                    zip_buffer.seek(0)
                    zip_data = zip_buffer.getvalue()
                    
                    file_names = [r['filename'] for r in text_results]
                    display_name = f"{file_names[0]}" if len(file_names) == 1 else f"{file_names[0]} 외 {len(file_names)-1}개"
                    save_download_file(zip_data, display_name, zip_filename)
                    
                    st.download_button(
                        label="📦 전체 다운로드 (ZIP)",
                        data=zip_data,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    st.caption("💡 24시간 동안 사이드바에서 다시 받을 수 있어요")
                    
                    if send_email_option and user_emails:
                        with st.spinner("📧 이메일 발송 중..."):
                            email_body = generate_email_body(
                                text_results, 
                                total_elapsed_time, 
                                costs['total_krw']
                            )
                            
                            attachments = [(zip_filename, zip_data)]
                            success, msg = send_email(
                                user_emails,
                                f"[캐피 인터뷰] 인터뷰 정리 결과 - {get_kst_now().strftime('%Y-%m-%d')}",
                                email_body,
                                attachments
                            )
                            if success:
                                st.success("✅ 이메일 발송 완료!")
                                st.caption("📬 수신자: " + ", ".join(user_emails))
                            else:
                                st.warning(f"⚠️ 이메일 실패: {msg}")

if __name__ == "__main__":
    main()
