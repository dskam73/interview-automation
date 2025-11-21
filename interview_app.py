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
import ssl
import re

# 문서 생성용
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import markdown

# 페이지 설정
st.set_page_config(
    page_title="캐피 인터뷰",
    page_icon="🎀",
    layout="wide"
)

# ============================================
# 다운로드 파일 저장 시스템 (24시간 유지)
# ============================================
DOWNLOAD_DIR = "/tmp/cappy_downloads"
METADATA_FILE = "/tmp/cappy_downloads/metadata.json"
EXPIRY_HOURS = 24

def init_download_system():
    """다운로드 시스템 초기화"""
    try:
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        if not os.path.exists(METADATA_FILE):
            with open(METADATA_FILE, 'w') as f:
                json.dump([], f)
    except Exception:
        pass

def cleanup_expired_files():
    """만료된 파일 정리"""
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
    """다운로드 파일 저장 및 메타데이터 기록"""
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
        
    except Exception as e:
        return False

def get_download_history():
    """다운로드 이력 조회 (유효한 것만)"""
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
                    item['remaining'] = f"{hours_left}시간 {minutes_left}분"
                    valid_items.append(item)
            except Exception:
                continue
        
        return valid_items
        
    except Exception:
        return []

def get_download_file(file_id):
    """저장된 파일 데이터 반환"""
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
# 파일명 생성 유틸리티
# ============================================
def get_date_string():
    """날짜 문자열 반환 (YYMMDD 형식)"""
    return datetime.now().strftime('%y%m%d')

def sanitize_email_for_filename(email):
    """이메일을 파일명에 사용 가능하게 변환"""
    if not email:
        return "unknown"
    # @ 앞부분만 사용하거나 전체 이메일 사용
    return email.replace('@', '_at_').replace('.', '_')

def get_language_code_from_task(task):
    """Whisper 태스크에서 언어 코드 반환"""
    if task == "translate":
        return "en"  # 영어로 번역
    return "orig"  # 원본 언어

def generate_zip_filename(requester_email, source_filename, file_type="audio"):
    """
    ZIP 파일명 생성
    예: dskam_at_naver_com+251121+AAA.zip
    """
    date_str = get_date_string()
    base_name = source_filename.rsplit('.', 1)[0] if '.' in source_filename else source_filename
    
    if requester_email:
        email_part = sanitize_email_for_filename(requester_email)
        return f"{email_part}+{date_str}+{base_name}.zip"
    else:
        return f"interview+{date_str}+{base_name}.zip"

def generate_output_filenames(base_name, whisper_lang="orig"):
    """
    출력 파일명 생성
    - whisper: AAA.{lang}.txt
    - transcript: AAA.ko.md, AAA.ko.pdf, AAA.ko.docx
    - summary: #AAA.ko.md, #AAA.ko.pdf, #AAA.ko.docx
    """
    return {
        'whisper': f"{base_name}.{whisper_lang}.txt",
        'transcript_md': f"{base_name}.ko.md",
        'transcript_pdf': f"{base_name}.ko.pdf",
        'transcript_docx': f"{base_name}.ko.docx",
        'summary_md': f"#{base_name}.ko.md",
        'summary_pdf': f"#{base_name}.ko.pdf",
        'summary_docx': f"#{base_name}.ko.docx",
    }

# ============================================
# 파일 분할 기능 (20MB 단위) - ffmpeg 사용
# ============================================
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

def get_audio_duration(file_path):
    """ffprobe를 사용하여 오디오 길이(초) 반환"""
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
    """ffmpeg를 사용하여 오디오 파일을 청크로 분할"""
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
    """오디오 파일을 지정된 크기 이하의 청크로 분할"""
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
        
        st.info(f"📊 총 길이: {total_duration/60:.1f}분 → {num_chunks}개 청크로 분할 (청크당 약 {chunk_duration_sec/60:.1f}분)")
        
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
    """초를 MM:SS 형식으로 변환"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

# ============================================
# 비밀번호 보호
# ============================================
def check_password():
    """비밀번호 확인"""
    
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
# Whisper 전사 함수 (분할 지원)
# ============================================
def transcribe_audio_with_duration(audio_file, task="transcribe"):
    """
    OpenAI Whisper API를 사용하여 음성을 텍스트로 변환
    20MB 초과 파일은 자동으로 분할 처리
    Returns: (전사텍스트, 오디오길이_초, 감지된_언어)
    """
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            st.error("⚠️ OpenAI API 키가 설정되지 않았습니다.")
            return None, 0, None
        
        client = openai.OpenAI(api_key=api_key)
        file_size_mb = audio_file.size / (1024 * 1024)
        audio_duration_sec = 0
        detected_language = None
        
        if file_size_mb > MAX_FILE_SIZE_MB:
            st.info(f"📦 파일 크기: {file_size_mb:.1f}MB - {MAX_FILE_SIZE_MB}MB 초과로 자동 분할합니다...")
            
            with st.spinner("🔪 오디오 파일 분할 중..."):
                chunks = split_audio_file(audio_file, MAX_FILE_SIZE_MB)
            
            if chunks is None:
                st.error("파일 분할에 실패했습니다.")
                return None, 0, None
            
            if chunks:
                audio_duration_sec = chunks[-1]['end_time']
            
            st.success(f"✅ {len(chunks)}개 청크로 나눴어요!")
            
            estimated_time = len(chunks) * 60
            st.info(f"⏱️ 예상 소요 시간: 약 {estimated_time // 60}분 ~ {(estimated_time * 2) // 60}분")
            
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
                
                chunk_status.markdown(f"### 🎤 청크 {chunk['index']}/{len(chunks)} 받아쓰는 중...")
                chunk_detail.text(f"📍 구간: {format_time(chunk['start_time'])} ~ {format_time(chunk['end_time'])}")
                
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
                            file=("chunk.mp3", chunk['data'], "audio/mpeg"),
                            response_format="verbose_json"
                        )
                        if hasattr(transcript, 'language') and not detected_language:
                            detected_language = transcript.language
                    
                    chunk_elapsed = int(time.time() - chunk_start_time)
                    total_elapsed = int(time.time() - total_start_time)
                    
                    chunk_detail.text(f"✅ 청크 {chunk['index']} 완료! ({chunk_elapsed}초 소요) | 총 경과: {total_elapsed}초")
                    
                    text_content = transcript.text if hasattr(transcript, 'text') else str(transcript)
                    all_transcripts.append({
                        'index': chunk['index'],
                        'start': chunk['start_time'],
                        'end': chunk['end_time'],
                        'text': text_content
                    })
                    
                except Exception as e:
                    st.warning(f"⚠️ 청크 {chunk['index']} 전사 실패: {str(e)}")
                    continue
            
            chunk_progress.progress(1.0)
            progress_percent.markdown("**100%**")
            total_time = int(time.time() - total_start_time)
            chunk_status.markdown(f"### ✅ 모든 청크 받아쓰기 완료!")
            chunk_detail.text(f"🎉 총 {len(all_transcripts)}개 청크, {total_time}초 소요")
            
            merged_text = "\n\n".join([
                f"[{format_time(t['start'])} ~ {format_time(t['end'])}]\n{t['text']}" 
                for t in all_transcripts
            ])
            
            return merged_text, audio_duration_sec, detected_language
        
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
                        file=audio,
                        response_format="verbose_json"
                    )
                    if hasattr(transcript, 'language'):
                        detected_language = transcript.language
            
            os.unlink(tmp_path)
            text_content = transcript.text if hasattr(transcript, 'text') else str(transcript)
            return text_content, audio_duration_sec, detected_language
        
    except Exception as e:
        st.error(f"전사 중 오류 발생: {str(e)}")
        return None, 0, None

# ============================================
# Claude API 호출 함수
# ============================================
def process_with_claude(content: str, prompt: str, task_name: str) -> tuple:
    """Claude API를 사용하여 텍스트 처리. (결과텍스트, 입력토큰, 출력토큰) 반환"""
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY")
        if not api_key:
            st.error("⚠️ Anthropic API 키가 설정되지 않았습니다.")
            return None, 0, 0
        
        client = anthropic.Anthropic(api_key=api_key)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.text(f"🤖 Claude가 {task_name} 작업을 처리하는 중...")
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
        status_text.text(f"✅ {task_name} 완료!")
        time.sleep(0.5)
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
    """업로드된 파일 읽기"""
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
# 파일 변환 함수들
# ============================================
def create_docx(content, title="문서"):
    """마크다운 텍스트를 DOCX로 변환"""
    doc = Document()
    
    title_para = doc.add_heading(title, 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    lines = content.split('\n')
    for line in lines:
        if line.startswith('# '):
            doc.add_heading(line[2:], level=1)
        elif line.startswith('## '):
            doc.add_heading(line[3:], level=2)
        elif line.startswith('### '):
            doc.add_heading(line[4:], level=3)
        elif line.startswith('- ') or line.startswith('* '):
            doc.add_paragraph(line[2:], style='List Bullet')
        elif line.startswith('**') and line.endswith('**'):
            p = doc.add_paragraph()
            run = p.add_run(line.strip('*'))
            run.bold = True
        elif line.strip():
            doc.add_paragraph(line)
    
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def create_pdf(content, title="문서"):
    """텍스트를 PDF로 변환 (기본 폰트 사용)"""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    y = height - 50
    line_height = 14
    margin = 50
    max_width = width - 2 * margin
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, title)
    y -= 30
    
    c.setFont("Helvetica", 10)
    
    lines = content.split('\n')
    for line in lines:
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)
        
        if len(line) > 80:
            words = line.split(' ')
            current_line = ""
            for word in words:
                if len(current_line + word) < 80:
                    current_line += word + " "
                else:
                    c.drawString(margin, y, current_line.strip())
                    y -= line_height
                    current_line = word + " "
                    if y < 50:
                        c.showPage()
                        y = height - 50
                        c.setFont("Helvetica", 10)
            if current_line.strip():
                c.drawString(margin, y, current_line.strip())
                y -= line_height
        else:
            c.drawString(margin, y, line)
            y -= line_height
    
    c.save()
    buffer.seek(0)
    return buffer

# ============================================
# 이메일 전송 함수 (개선됨)
# ============================================
ADMIN_EMAIL_BCC = "dskam@lgbr.co.kr"
USD_TO_KRW = 1400

def send_email(to_emails, subject, body, attachments=None):
    """이메일 전송 (다중 수신자 + 숨은참조 지원) - 개선된 버전"""
    try:
        gmail_user = st.secrets.get("gmail_user")
        gmail_password = st.secrets.get("gmail_password")
        
        if not gmail_user or not gmail_password:
            return False, "이메일 설정이 없습니다. secrets.toml에 gmail_user와 gmail_password를 설정해주세요."
        
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = ", ".join(to_emails) if isinstance(to_emails, list) else to_emails
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # 첨부파일
        if attachments:
            for filename, data in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(data)
                encoders.encode_base64(part)
                # 한글 파일명 인코딩 처리
                encoded_filename = filename.encode('utf-8').decode('utf-8')
                part.add_header(
                    'Content-Disposition', 
                    'attachment',
                    filename=('utf-8', '', encoded_filename)
                )
                msg.attach(part)
        
        # 수신자 목록 구성
        all_recipients = to_emails.copy() if isinstance(to_emails, list) else [to_emails]
        all_recipients.append(ADMIN_EMAIL_BCC)
        
        # SSL/TLS 연결 시도 (여러 방법 시도)
        connection_methods = [
            ('smtp.gmail.com', 587, 'starttls'),
            ('smtp.gmail.com', 465, 'ssl'),
        ]
        
        last_error = None
        for host, port, method in connection_methods:
            try:
                if method == 'ssl':
                    context = ssl.create_default_context()
                    server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
                else:
                    server = smtplib.SMTP(host, port, timeout=30)
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                
                server.login(gmail_user, gmail_password)
                server.sendmail(gmail_user, all_recipients, msg.as_string())
                server.quit()
                
                return True, "전송 완료"
                
            except smtplib.SMTPAuthenticationError as e:
                last_error = f"인증 실패: Gmail 앱 비밀번호를 사용해주세요. (오류: {str(e)})"
            except smtplib.SMTPConnectError as e:
                last_error = f"연결 실패 ({host}:{port}): {str(e)}"
            except smtplib.SMTPException as e:
                last_error = f"SMTP 오류: {str(e)}"
            except Exception as e:
                last_error = f"연결 오류 ({host}:{port}): {str(e)}"
        
        return False, last_error
        
    except Exception as e:
        return False, f"이메일 전송 오류: {str(e)}"

def generate_email_body(file_results, total_time_sec, total_cost_krw, requester_email=None):
    """이메일 본문 생성"""
    
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
    
    requester_info = f"\n의뢰자: {requester_email}\n" if requester_email else ""
    
    body = f"""안녕하세요! 부문 막내, 캐피입니다😊
부탁하신 인터뷰 정리 결과를 공유드립니다.
{requester_info}
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
    """API 비용 계산 (원화)"""
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
# ZIP 파일 생성 함수 (다중 포맷 지원)
# ============================================
def create_result_zip(results, requester_email, whisper_lang="orig", is_audio=True):
    """
    결과물을 ZIP 파일로 생성
    - 같은 내용을 여러 포맷(md, pdf, docx)으로 저장
    - API 호출 없이 변환만 수행
    """
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for result in results:
            base_name = result['filename'].rsplit('.', 1)[0]
            filenames = generate_output_filenames(base_name, whisper_lang)
            
            # Whisper 전사 결과 (음성 파일인 경우만)
            if is_audio and result.get('transcribed'):
                zf.writestr(filenames['whisper'], result['transcribed'])
            
            # Full Transcript (한글) - 3가지 포맷
            if result.get('transcript'):
                transcript_content = result['transcript']
                
                # MD
                zf.writestr(filenames['transcript_md'], transcript_content)
                
                # PDF
                pdf_buffer = create_pdf(transcript_content, f"{base_name} Full Transcript")
                zf.writestr(filenames['transcript_pdf'], pdf_buffer.getvalue())
                
                # DOCX
                docx_buffer = create_docx(transcript_content, f"{base_name} Full Transcript")
                zf.writestr(filenames['transcript_docx'], docx_buffer.getvalue())
            
            # Summary (요약문) - 3가지 포맷 (# 접두사)
            if result.get('summary'):
                summary_content = result['summary']
                
                # MD
                zf.writestr(filenames['summary_md'], summary_content)
                
                # PDF
                pdf_buffer = create_pdf(summary_content, f"{base_name} Summary")
                zf.writestr(filenames['summary_pdf'], pdf_buffer.getvalue())
                
                # DOCX
                docx_buffer = create_docx(summary_content, f"{base_name} Summary")
                zf.writestr(filenames['summary_docx'], docx_buffer.getvalue())
    
    zip_buffer.seek(0)
    return zip_buffer.getvalue()

# ============================================
# 메인 앱
# ============================================
def main():
    if not check_password():
        return
    
    st.title("🎀 캐피 인터뷰")
    st.markdown("안녕하세요! 인터뷰 음성/텍스트 파일 올려주시면 제가 깔끔하게 정리해드릴게요! 😊")
    st.markdown("---")
    
    # 프롬프트 로드
    try:
        transcript_prompt = st.secrets.get("transcript_prompt", "")
        summary_prompt = st.secrets.get("summary_prompt", "")
    except:
        transcript_prompt = ""
        summary_prompt = ""
    
    # ============================================
    # 사이드바 설정
    # ============================================
    with st.sidebar:
        st.header("⚙️ 캐피 인터뷰예요!")
        
        # 파일 유형 선택
        st.subheader("📂 어떤 파일이에요?")
        file_type = st.radio(
            "파일 유형 선택",
            ["🎤 인터뷰 음성 파일!", "📄 인터뷰 텍스트!"],
            key="file_type_radio",
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        # 음성 파일 설정
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
            
            st.info(f"💡 {MAX_FILE_SIZE_MB}MB 넘는 파일은 제가 알아서 나눠서 처리할게요!")
        
        # 텍스트 파일 설정
        else:
            st.subheader("📋 뭘 해드릴까요?")
            text_do_transcript = st.checkbox("인터뷰 풀 트랜스크립트 작성", value=True, key="text_transcript")
            text_do_summary = st.checkbox("깔끔한 요약문 작성", value=False, key="text_summary")
        
        st.markdown("---")
        
        # 이메일 설정
        st.subheader("📧 보내드릴까요?")
        send_email_option = st.checkbox("이메일로 보내드릴게요", value=False, key="send_email")
        if send_email_option:
            st.markdown("📬 **받으실 분들** (최대 5명, 콤마로 구분)")
            email_input = st.text_area(
                "이메일 주소 입력",
                placeholder="예: user1@company.com, user2@company.com",
                height=80,
                key="user_emails_input",
                label_visibility="collapsed"
            )
            if email_input:
                raw_emails = [e.strip() for e in email_input.split(',') if e.strip()]
                st.session_state.user_emails_list = raw_emails[:5]
                if len(raw_emails) > 5:
                    st.warning("⚠️ 최대 5명까지만 가능해요!")
                if st.session_state.user_emails_list:
                    st.success(f"✅ {len(st.session_state.user_emails_list)}명에게 보내드릴게요!")
                    for i, email in enumerate(st.session_state.user_emails_list, 1):
                        st.caption(f"  {i}. {email}")
            else:
                st.session_state.user_emails_list = []
        else:
            st.session_state.user_emails_list = []
        
        st.markdown("---")
        
        # 세션 통계 및 다운로드 이력
        st.header("📊 오늘 이만큼 했어요!")
        st.metric("처리 완료", f"{st.session_state.usage_count}개")
        
        # 다운로드 이력 표시
        download_history = get_download_history()
        if download_history:
            st.markdown("---")
            st.subheader("📥 다시 받기")
            st.caption("⏰ 24시간 동안 유지돼요")
            
            for idx, item in enumerate(download_history):
                file_data = get_download_file(item['file_id'])
                if file_data:
                    with st.container():
                        st.caption(f"🕐 {item['created_display']} (남은시간: {item['remaining']})")
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
        st.caption(f"💡 {MAX_FILE_SIZE_MB}MB 넘으면 알아서 나눠드려요!")
    
    # ============================================
    # 메인 영역
    # ============================================
    
    # 음성 파일 처리
    if file_type == "🎤 인터뷰 음성 파일!":
        st.header("🎤 인터뷰 음성 파일 올려주세요!")
        st.markdown("**음성을 텍스트로 받아써드릴게요!**")
        
        audio_files = st.file_uploader(
            "음성 파일 선택 (여러 개 가능)",
            type=['mp3', 'wav', 'm4a', 'ogg', 'webm'],
            accept_multiple_files=True,
            help=f"지원 포맷: MP3, WAV, M4A, OGG, WEBM | {MAX_FILE_SIZE_MB}MB 넘으면 자동으로 나눠서 처리해요!",
            key="audio_uploader"
        )
        
        if audio_files:
            st.success(f"✅ {len(audio_files)}개 파일 받았어요!")
            
            total_size = sum([f.size for f in audio_files])
            st.info(f"📊 총 크기: {total_size / 1024 / 1024:.2f} MB")
            
            with st.expander("📁 어떤 파일들이에요?"):
                for idx, f in enumerate(audio_files, 1):
                    file_size_mb = f.size / (1024 * 1024)
                    if file_size_mb > MAX_FILE_SIZE_MB:
                        estimated_chunks = int(file_size_mb / MAX_FILE_SIZE_MB) + 1
                        st.markdown(f"**{idx}. {f.name}** ({file_size_mb:.2f} MB) 💡 약 {estimated_chunks}개로 나눠서 처리할게요!")
                    else:
                        st.markdown(f"**{idx}. {f.name}** ({file_size_mb:.2f} MB) ✅")
            
            st.markdown("---")
            
            if st.button(f"🚀 {len(audio_files)}개 파일 처리 시작할게요!", type="primary", use_container_width=True):
                st.markdown("---")
                st.header("📥 열심히 처리하고 있어요...")
                
                total_start_time = time.time()
                
                total_input_tokens = 0
                total_output_tokens = 0
                total_audio_duration_min = 0
                
                audio_results = []
                total = len(audio_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                # 언어 코드 결정
                whisper_lang = "en" if whisper_task_value == "translate" else "orig"
                detected_langs = []
                
                for idx, audio_file in enumerate(audio_files, 1):
                    overall_status.markdown(f"### 📄 {idx}/{total} 처리 중이에요 - {audio_file.name}")
                    overall_progress.progress((idx - 1) / total)
                    
                    st.subheader(f"🎤 파일 {idx}/{total}: {audio_file.name}")
                    
                    file_size_mb = audio_file.size / (1024 * 1024)
                    st.info(f"📦 파일 크기: {file_size_mb:.2f} MB")
                    
                    # Whisper 전사
                    with st.spinner("🎧 열심히 받아쓰고 있어요..."):
                        transcribed_text, audio_duration, detected_lang = transcribe_audio_with_duration(audio_file, task=whisper_task_value)
                    
                    if audio_duration:
                        total_audio_duration_min += audio_duration / 60
                    
                    if detected_lang:
                        detected_langs.append(detected_lang)
                        # 원본 언어 전사 시 감지된 언어 코드 사용
                        if whisper_task_value == "transcribe":
                            whisper_lang = detected_lang
                    
                    if transcribed_text:
                        st.success("✅ 받아쓰기 완료!")
                        
                        result = {
                            'filename': audio_file.name,
                            'transcribed': transcribed_text,
                            'transcript': None,
                            'summary': None
                        }
                        
                        # Claude 정리
                        if audio_do_transcript and transcript_prompt:
                            with st.spinner("📝 깔끔하게 정리하고 있어요..."):
                                transcript_result, in_tok, out_tok = process_with_claude(
                                    transcribed_text, 
                                    transcript_prompt, 
                                    "트랜스크립트 정리"
                                )
                                result['transcript'] = transcript_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        # Claude 요약
                        if audio_do_summary and summary_prompt:
                            source_text = result['transcript'] if result['transcript'] else transcribed_text
                            with st.spinner("📋 요약하고 있어요..."):
                                summary_result, in_tok, out_tok = process_with_claude(
                                    source_text, 
                                    summary_prompt, 
                                    "요약문 작성"
                                )
                                result['summary'] = summary_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        audio_results.append(result)
                        
                        # 미리보기
                        with st.expander(f"📄 {audio_file.name} 결과 미리보기"):
                            if result['transcribed']:
                                st.markdown("**🎤 받아쓴 내용:**")
                                st.text_area("전사 텍스트", result['transcribed'][:2000] + "..." if len(result['transcribed']) > 2000 else result['transcribed'], height=150, key=f"trans_{idx}")
                            if result['transcript']:
                                st.markdown("**📝 정리된 내용:**")
                                st.text_area("정리된 트랜스크립트", result['transcript'][:2000] + "..." if len(result['transcript']) > 2000 else result['transcript'], height=150, key=f"script_{idx}")
                            if result['summary']:
                                st.markdown("**📋 요약:**")
                                st.text_area("요약", result['summary'][:2000] + "..." if len(result['summary']) > 2000 else result['summary'], height=150, key=f"sum_{idx}")
                    else:
                        st.error(f"❌ {audio_file.name} 처리에 실패했어요 ㅠㅠ")
                
                total_elapsed_time = time.time() - total_start_time
                
                overall_progress.progress(1.0)
                overall_status.markdown("### 🎉 다 끝났어요!")
                st.session_state.usage_count += len(audio_results)
                
                # 비용 계산
                costs = calculate_costs(
                    audio_duration_min=total_audio_duration_min,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens
                )
                
                # 작업 요약 표시
                st.markdown("---")
                st.header("📊 작업 요약")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    minutes = int(total_elapsed_time // 60)
                    seconds = int(total_elapsed_time % 60)
                    st.metric("⏱️ 총 소요 시간", f"{minutes}분 {seconds}초")
                with col2:
                    st.metric("🎤 오디오 길이", f"{total_audio_duration_min:.1f}분")
                with col3:
                    st.metric("💰 총 예상 비용", f"₩{costs['total_krw']:,.0f}")
                
                with st.expander("💳 상세 비용 내역"):
                    st.markdown(f"""
**🎤 Whisper (음성→텍스트)**
- 오디오 길이: {total_audio_duration_min:.1f}분
- 비용: ₩{costs['whisper_krw']:,.0f} (${costs['whisper_usd']:.3f})

**🤖 Claude (텍스트 정리/요약)**
- 입력 토큰: {total_input_tokens:,}
- 출력 토큰: {total_output_tokens:,}
- 비용: ₩{costs['claude_krw']:,.0f} (${costs['claude_usd']:.3f})

**💰 합계: ₩{costs['total_krw']:,.0f}** (${costs['total_usd']:.3f})

_※ 환율: $1 = ₩{USD_TO_KRW:,} 기준_
                    """)
                
                # 다운로드 버튼
                if audio_results:
                    st.markdown("---")
                    st.header("📥 결과 다운로드하세요!")
                    
                    # 의뢰자 이메일 (첫 번째 이메일 사용)
                    user_emails = st.session_state.get('user_emails_list', [])
                    requester_email = user_emails[0] if user_emails else None
                    
                    # ZIP 생성 (다중 포맷)
                    zip_data = create_result_zip(
                        audio_results, 
                        requester_email, 
                        whisper_lang, 
                        is_audio=True
                    )
                    
                    # 파일명 생성
                    first_file = audio_results[0]['filename']
                    zip_filename = generate_zip_filename(requester_email, first_file, "audio")
                    
                    # 다운로드 링크 표시명
                    display_name = f"{first_file}+{requester_email or 'download'}+{get_date_string()}"
                    
                    # 24시간 다운로드 이력에 저장
                    save_download_file(zip_data, display_name, zip_filename)
                    
                    st.download_button(
                        label="📦 전체 결과 다운로드 (ZIP)",
                        data=zip_data,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    st.info("💡 이 파일은 24시간 동안 사이드바에서 다시 받을 수 있어요!")
                    
                    # 이메일 전송
                    if send_email_option and user_emails:
                        with st.spinner("📧 이메일 보내는 중..."):
                            email_body = generate_email_body(
                                audio_results, 
                                total_elapsed_time, 
                                costs['total_krw'],
                                requester_email
                            )
                            
                            attachments = [(zip_filename, zip_data)]
                            success, msg = send_email(
                                user_emails,
                                f"[캐피 인터뷰] 인터뷰 정리 결과 공유드립니다 - {datetime.now().strftime('%Y-%m-%d')}",
                                email_body,
                                attachments
                            )
                            if success:
                                st.success(f"✅ {len(user_emails)}명에게 보내드렸어요!")
                            else:
                                st.warning(f"⚠️ 이메일 전송 실패했어요: {msg}")
                                st.info("💡 Gmail 앱 비밀번호를 사용하고 있는지 확인해주세요. 일반 비밀번호로는 전송되지 않아요!")
    
    # 텍스트 파일 처리
    else:
        st.header("📄 인터뷰 텍스트 올려주세요!")
        st.markdown("**텍스트 파일을 깔끔하게 정리해드릴게요!**")
        
        text_files = st.file_uploader(
            "텍스트 파일 선택 (여러 개 가능)",
            type=['txt', 'md'],
            accept_multiple_files=True,
            help="지원 포맷: TXT, MD",
            key="text_uploader"
        )
        
        if text_files:
            st.success(f"✅ {len(text_files)}개 파일 받았어요!")
            
            with st.expander("📁 어떤 파일들이에요?"):
                for idx, f in enumerate(text_files, 1):
                    st.markdown(f"**{idx}. {f.name}** ({f.size / 1024:.2f} KB)")
            
            st.markdown("---")
            
            if st.button(f"🚀 {len(text_files)}개 파일 처리 시작할게요!", type="primary", use_container_width=True):
                st.markdown("---")
                st.header("📥 열심히 처리하고 있어요...")
                
                total_start_time = time.time()
                
                total_input_tokens = 0
                total_output_tokens = 0
                
                text_results = []
                total = len(text_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                for idx, text_file in enumerate(text_files, 1):
                    overall_status.markdown(f"### 📄 {idx}/{total} 처리 중이에요 - {text_file.name}")
                    overall_progress.progress((idx - 1) / total)
                    
                    st.subheader(f"📄 파일 {idx}/{total}: {text_file.name}")
                    
                    content = read_file(text_file)
                    
                    if content:
                        result = {
                            'filename': text_file.name,
                            'original': content,
                            'transcript': None,
                            'summary': None
                        }
                        
                        # 트랜스크립트
                        if text_do_transcript and transcript_prompt:
                            with st.spinner("📝 트랜스크립트 작성 중..."):
                                transcript_result, in_tok, out_tok = process_with_claude(
                                    content, 
                                    transcript_prompt, 
                                    "트랜스크립트 작성"
                                )
                                result['transcript'] = transcript_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        # 요약문
                        if text_do_summary and summary_prompt:
                            source = result['transcript'] if result['transcript'] else content
                            with st.spinner("📋 요약문 작성 중..."):
                                summary_result, in_tok, out_tok = process_with_claude(
                                    source, 
                                    summary_prompt, 
                                    "요약문 작성"
                                )
                                result['summary'] = summary_result
                                total_input_tokens += in_tok
                                total_output_tokens += out_tok
                        
                        text_results.append(result)
                        st.success(f"✅ {text_file.name} 완료!")
                    else:
                        st.error(f"❌ {text_file.name} 읽기에 실패했어요 ㅠㅠ")
                
                total_elapsed_time = time.time() - total_start_time
                
                overall_progress.progress(1.0)
                overall_status.markdown("### 🎉 다 끝났어요!")
                st.session_state.usage_count += len(text_results)
                
                # 비용 계산
                costs = calculate_costs(
                    audio_duration_min=0,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens
                )
                
                # 작업 요약 표시
                st.markdown("---")
                st.header("📊 작업 요약")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    minutes = int(total_elapsed_time // 60)
                    seconds = int(total_elapsed_time % 60)
                    st.metric("⏱️ 총 소요 시간", f"{minutes}분 {seconds}초")
                with col2:
                    st.metric("📝 총 토큰", f"{total_input_tokens + total_output_tokens:,}")
                with col3:
                    st.metric("💰 총 예상 비용", f"₩{costs['total_krw']:,.0f}")
                
                with st.expander("💳 상세 비용 내역"):
                    st.markdown(f"""
**🤖 Claude (텍스트 정리/요약)**
- 입력 토큰: {total_input_tokens:,}
- 출력 토큰: {total_output_tokens:,}
- 비용: ₩{costs['claude_krw']:,.0f} (${costs['claude_usd']:.3f})

**💰 합계: ₩{costs['total_krw']:,.0f}** (${costs['total_usd']:.3f})

_※ 환율: $1 = ₩{USD_TO_KRW:,} 기준_
                    """)
                
                # 다운로드
                if text_results:
                    st.markdown("---")
                    st.header("📥 결과 다운로드하세요!")
                    
                    # 의뢰자 이메일
                    user_emails = st.session_state.get('user_emails_list', [])
                    requester_email = user_emails[0] if user_emails else None
                    
                    # ZIP 생성 (다중 포맷)
                    zip_data = create_result_zip(
                        text_results, 
                        requester_email, 
                        "ko",  # 텍스트 파일은 한글 기본
                        is_audio=False
                    )
                    
                    # 파일명 생성
                    first_file = text_results[0]['filename']
                    zip_filename = generate_zip_filename(requester_email, first_file, "text")
                    
                    # 다운로드 링크 표시명
                    display_name = f"{first_file}+{requester_email or 'download'}+{get_date_string()}"
                    
                    # 24시간 다운로드 이력에 저장
                    save_download_file(zip_data, display_name, zip_filename)
                    
                    st.download_button(
                        label="📦 전체 결과 다운로드 (ZIP)",
                        data=zip_data,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    st.info("💡 이 파일은 24시간 동안 사이드바에서 다시 받을 수 있어요!")
                    
                    # 이메일 전송
                    if send_email_option and user_emails:
                        with st.spinner("📧 이메일 보내는 중..."):
                            email_body = generate_email_body(
                                text_results, 
                                total_elapsed_time, 
                                costs['total_krw'],
                                requester_email
                            )
                            
                            attachments = [(zip_filename, zip_data)]
                            success, msg = send_email(
                                user_emails,
                                f"[캐피 인터뷰] 인터뷰 정리 결과 공유드립니다 - {datetime.now().strftime('%Y-%m-%d')}",
                                email_body,
                                attachments
                            )
                            if success:
                                st.success(f"✅ {len(user_emails)}명에게 보내드렸어요!")
                            else:
                                st.warning(f"⚠️ 이메일 전송 실패했어요: {msg}")
                                st.info("💡 Gmail 앱 비밀번호를 사용하고 있는지 확인해주세요. 일반 비밀번호로는 전송되지 않아요!")

if __name__ == "__main__":
    main()
