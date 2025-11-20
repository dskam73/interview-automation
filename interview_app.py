import streamlit as st
import anthropic
import openai
import tempfile
import time
from datetime import datetime
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

# 세션 상태 초기화
if 'usage_count' not in st.session_state:
    st.session_state.usage_count = 0
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "audio"

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
    """
    ffmpeg를 사용하여 오디오 파일을 청크로 분할
    
    Args:
        input_path: 입력 파일 경로
        output_dir: 출력 디렉토리
        chunk_duration_sec: 청크 길이 (초), 기본 10분
    
    Returns:
        list: 분할된 청크 정보 리스트
    """
    try:
        # 전체 길이 확인
        total_duration = get_audio_duration(input_path)
        if total_duration is None:
            return None
        
        chunks = []
        start_time = 0
        chunk_index = 1
        
        while start_time < total_duration:
            end_time = min(start_time + chunk_duration_sec, total_duration)
            output_path = os.path.join(output_dir, f"chunk_{chunk_index:03d}.mp3")
            
            # ffmpeg로 청크 추출
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-ss', str(start_time),
                '-t', str(chunk_duration_sec),
                '-acodec', 'libmp3lame',
                '-ab', '128k',
                '-ar', '44100',
                '-ac', '1',  # 모노로 변환하여 크기 절약
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, check=True)
            
            # 청크 정보 저장
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
    """
    오디오 파일을 지정된 크기 이하의 청크로 분할
    
    Args:
        audio_file: Streamlit 업로드 파일 객체
        max_size_mb: 최대 파일 크기 (MB)
    
    Returns:
        list: 분할된 오디오 청크들의 정보 리스트
    """
    try:
        file_size_mb = audio_file.size / (1024 * 1024)
        
        # 파일 크기가 제한 이하면 분할 불필요
        if file_size_mb <= max_size_mb:
            return None
        
        # 임시 디렉토리 생성
        temp_dir = tempfile.mkdtemp()
        file_extension = audio_file.name.split('.')[-1].lower()
        input_path = os.path.join(temp_dir, f"input.{file_extension}")
        
        # 파일 저장
        with open(input_path, 'wb') as f:
            f.write(audio_file.read())
        
        # 파일 포인터 리셋
        audio_file.seek(0)
        
        # 전체 길이 확인
        total_duration = get_audio_duration(input_path)
        if total_duration is None:
            return None
        
        # 청크 길이 계산 (파일 크기 기반)
        # 예: 80MB 파일 → 4개 청크 필요 → 각 청크는 전체 길이/4
        num_chunks = int(file_size_mb / max_size_mb) + 1
        chunk_duration_sec = total_duration / num_chunks
        
        # 최소 60초, 최대 1200초 (20분) 제한
        chunk_duration_sec = max(60, min(chunk_duration_sec, 1200))
        
        st.info(f"📊 총 길이: {total_duration/60:.1f}분 → {num_chunks}개 청크로 분할 (청크당 약 {chunk_duration_sec/60:.1f}분)")
        
        # 분할 실행
        chunks = split_audio_with_ffmpeg(input_path, temp_dir, chunk_duration_sec)
        
        if chunks:
            # 각 청크의 바이트 데이터 로드
            for chunk in chunks:
                with open(chunk['path'], 'rb') as f:
                    chunk['data'] = io.BytesIO(f.read())
                # 임시 파일 삭제
                os.unlink(chunk['path'])
            
            # 입력 파일 삭제
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
def transcribe_audio(audio_file, task="transcribe"):
    """
    OpenAI Whisper API를 사용하여 음성을 텍스트로 변환
    20MB 초과 파일은 자동으로 분할 처리
    """
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            st.error("⚠️ OpenAI API 키가 설정되지 않았습니다.")
            return None
        
        client = openai.OpenAI(api_key=api_key)
        file_size_mb = audio_file.size / (1024 * 1024)
        
        # 파일 크기 확인 및 분할 처리
        if file_size_mb > MAX_FILE_SIZE_MB:
            st.info(f"📦 파일 크기: {file_size_mb:.1f}MB - {MAX_FILE_SIZE_MB}MB 초과로 자동 분할합니다...")
            
            # 파일 분할
            with st.spinner("🔪 오디오 파일 분할 중..."):
                chunks = split_audio_file(audio_file, MAX_FILE_SIZE_MB)
            
            if chunks is None:
                st.error("파일 분할에 실패했습니다.")
                return None
            
            st.success(f"✅ {len(chunks)}개 청크로 나눴어요!")
            
            # 예상 시간 안내
            estimated_time = len(chunks) * 60  # 청크당 약 1분 예상
            st.info(f"⏱️ 예상 소요 시간: 약 {estimated_time // 60}분 ~ {(estimated_time * 2) // 60}분")
            
            # 각 청크별 전사
            all_transcripts = []
            
            # 진행 상태 표시 영역
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
                # 진행률 계산
                progress_value = i / len(chunks)
                chunk_progress.progress(progress_value)
                progress_percent.markdown(f"**{int(progress_value * 100)}%**")
                
                # 상태 메시지
                chunk_status.markdown(f"### 🎤 청크 {chunk['index']}/{len(chunks)} 받아쓰는 중...")
                chunk_detail.text(f"📍 구간: {format_time(chunk['start_time'])} ~ {format_time(chunk['end_time'])}")
                
                # 청크 전사
                chunk['data'].seek(0)
                
                # 전사 시작 시간 기록
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
                    
                    # 소요 시간 계산
                    chunk_elapsed = int(time.time() - chunk_start_time)
                    total_elapsed = int(time.time() - total_start_time)
                    
                    # 완료 표시
                    chunk_detail.text(f"✅ 청크 {chunk['index']} 완료! ({chunk_elapsed}초 소요) | 총 경과: {total_elapsed}초")
                    
                    all_transcripts.append({
                        'index': chunk['index'],
                        'start': chunk['start_time'],
                        'end': chunk['end_time'],
                        'text': transcript.text
                    })
                    
                except Exception as e:
                    st.warning(f"⚠️ 청크 {chunk['index']} 전사 실패: {str(e)}")
                    continue
            
            # 최종 완료
            chunk_progress.progress(1.0)
            progress_percent.markdown("**100%**")
            total_time = int(time.time() - total_start_time)
            chunk_status.markdown(f"### ✅ 모든 청크 받아쓰기 완료!")
            chunk_detail.text(f"🎉 총 {len(all_transcripts)}개 청크, {total_time}초 소요")
            
            # 결과 병합
            merged_text = "\n\n".join([
                f"[{format_time(t['start'])} ~ {format_time(t['end'])}]\n{t['text']}" 
                for t in all_transcripts
            ])
            
            return merged_text
        
        else:
            # 분할 필요 없음 - 단일 파일 전사
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                tmp_file.write(audio_file.read())
                tmp_path = tmp_file.name
            
            # 파일 포인터 리셋
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
            return transcript.text
        
    except Exception as e:
        st.error(f"전사 중 오류 발생: {str(e)}")
        return None

# ============================================
# Claude API 호출 함수
# ============================================
def process_with_claude(content: str, prompt: str, task_name: str) -> str:
    """Claude API를 사용하여 텍스트 처리"""
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY")
        if not api_key:
            st.error("⚠️ Anthropic API 키가 설정되지 않았습니다.")
            return None
        
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
        
        return message.content[0].text
        
    except Exception as e:
        st.error(f"❌ 처리 중 오류 발생: {str(e)}")
        return None

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
    
    # 제목
    title_para = doc.add_heading(title, 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # 내용 추가
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
    
    # BytesIO로 저장
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def create_pdf(content, title="문서"):
    """텍스트를 PDF로 변환 (기본 폰트 사용)"""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # 기본 설정
    y = height - 50
    line_height = 14
    margin = 50
    max_width = width - 2 * margin
    
    # 제목
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, title)
    y -= 30
    
    # 내용
    c.setFont("Helvetica", 10)
    
    lines = content.split('\n')
    for line in lines:
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)
        
        # 긴 줄 처리
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
# 이메일 전송 함수
# ============================================
def send_email(to_email, subject, body, attachments=None):
    """이메일 전송"""
    try:
        gmail_user = st.secrets.get("gmail_user")
        gmail_password = st.secrets.get("gmail_password")
        
        if not gmail_user or not gmail_password:
            return False, "이메일 설정이 없습니다."
        
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # 첨부파일
        if attachments:
            for filename, data in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                msg.attach(part)
        
        # 전송
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        
        return True, "전송 완료"
        
    except Exception as e:
        return False, str(e)

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
        st.subheader("📑 어떤 파일이에요?")
        file_type = st.radio(
            "파일 유형 선택",
            ["🎤 인터뷰 음성 파일!", "📄 인터뷰 텍스트!"],
            key="file_type_radio",
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        # 음성 파일 설정
        if file_type == "🎤 인터뷰 음성 파일!":
            st.subheader("🔊 어떻게 받아쓸까요?")
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
            
            # 파일 크기 제한 안내
            st.info(f"💡 {MAX_FILE_SIZE_MB}MB 넘는 파일은 제가 알아서 나눠서 처리할게요!")
        
        # 텍스트 파일 설정
        else:
            st.subheader("📋 뭘 해드릴까요?")
            text_do_transcript = st.checkbox("인터뷰 풀 트랜스크립트 작성", value=True, key="text_transcript")
            text_do_summary = st.checkbox("깔끔한 요약문 작성", value=False, key="text_summary")
            
            st.markdown("---")
            
            st.subheader("📁 어떤 파일포맷이 편하세요?")
            output_md = st.checkbox("Markdown (.md)", value=True, key="out_md")
            output_docx = st.checkbox("Word (.docx)", value=False, key="out_docx")
            output_pdf = st.checkbox("PDF (.pdf)", value=False, key="out_pdf")
        
        st.markdown("---")
        
        # 이메일 설정
        st.subheader("📧 보내드릴까요?")
        send_email_option = st.checkbox("이메일로 보내드릴게요", value=False, key="send_email")
        user_email = ""
        if send_email_option:
            user_email = st.text_input("📬 받으실 주소 알려주세요!", key="user_email")
            if user_email:
                st.success(f"✅ {user_email}로 보내드릴게요!")
        
        st.markdown("---")
        
        # 세션 통계
        st.header("📊 오늘 이만큼 했어요!")
        st.metric("처리 완료", f"{st.session_state.usage_count}개")
        
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
            
            # 파일 목록 및 분할 예상 표시
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
                
                audio_results = []
                total = len(audio_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                for idx, audio_file in enumerate(audio_files, 1):
                    overall_status.markdown(f"### 🔄 {idx}/{total} 처리 중이에요 - {audio_file.name}")
                    overall_progress.progress((idx - 1) / total)
                    
                    st.subheader(f"🎤 파일 {idx}/{total}: {audio_file.name}")
                    
                    file_size_mb = audio_file.size / (1024 * 1024)
                    st.info(f"📦 파일 크기: {file_size_mb:.2f} MB")
                    
                    # Whisper 전사
                    with st.spinner("🎧 열심히 받아쓰고 있어요..."):
                        transcribed_text = transcribe_audio(audio_file, task=whisper_task_value)
                    
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
                                result['transcript'] = process_with_claude(
                                    transcribed_text, 
                                    transcript_prompt, 
                                    "트랜스크립트 정리"
                                )
                        
                        # Claude 요약
                        if audio_do_summary and summary_prompt:
                            source_text = result['transcript'] if result['transcript'] else transcribed_text
                            with st.spinner("📋 요약하고 있어요..."):
                                result['summary'] = process_with_claude(
                                    source_text, 
                                    summary_prompt, 
                                    "요약문 작성"
                                )
                        
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
                
                overall_progress.progress(1.0)
                overall_status.markdown("### 🎉 다 끝났어요!")
                st.session_state.usage_count += len(audio_results)
                
                # 다운로드 버튼
                if audio_results:
                    st.markdown("---")
                    st.header("📥 결과 다운로드하세요!")
                    
                    # ZIP 생성
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for result in audio_results:
                            base_name = result['filename'].rsplit('.', 1)[0]
                            
                            if result['transcribed']:
                                zf.writestr(f"{base_name}_whisper.txt", result['transcribed'])
                            if result['transcript']:
                                zf.writestr(f"{base_name}_transcript.md", result['transcript'])
                            if result['summary']:
                                zf.writestr(f"{base_name}_summary.md", result['summary'])
                    
                    zip_buffer.seek(0)
                    
                    st.download_button(
                        label="📦 전체 결과 다운로드 (ZIP)",
                        data=zip_buffer,
                        file_name=f"interview_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    # 이메일 전송
                    if send_email_option and user_email:
                        with st.spinner("📧 이메일 보내는 중..."):
                            zip_buffer.seek(0)
                            attachments = [(f"interview_results_{datetime.now().strftime('%Y%m%d')}.zip", zip_buffer.read())]
                            success, msg = send_email(
                                user_email,
                                f"[캐피 인터뷰] 결과 보내드려요! - {datetime.now().strftime('%Y-%m-%d')}",
                                f"{len(audio_results)}개 파일 처리 완료했어요!",
                                attachments
                            )
                            if success:
                                st.success(f"✅ {user_email}로 보내드렸어요!")
                            else:
                                st.warning(f"⚠️ 이메일 전송 실패했어요: {msg}")
    
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
                
                text_results = []
                total = len(text_files)
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                for idx, text_file in enumerate(text_files, 1):
                    overall_status.markdown(f"### 🔄 {idx}/{total} 처리 중이에요 - {text_file.name}")
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
                                result['transcript'] = process_with_claude(
                                    content, 
                                    transcript_prompt, 
                                    "트랜스크립트 작성"
                                )
                        
                        # 요약문
                        if text_do_summary and summary_prompt:
                            source = result['transcript'] if result['transcript'] else content
                            with st.spinner("📋 요약문 작성 중..."):
                                result['summary'] = process_with_claude(
                                    source, 
                                    summary_prompt, 
                                    "요약문 작성"
                                )
                        
                        text_results.append(result)
                        st.success(f"✅ {text_file.name} 완료!")
                    else:
                        st.error(f"❌ {text_file.name} 읽기에 실패했어요 ㅠㅠ")
                
                overall_progress.progress(1.0)
                overall_status.markdown("### 🎉 다 끝났어요!")
                st.session_state.usage_count += len(text_results)
                
                # 다운로드
                if text_results:
                    st.markdown("---")
                    st.header("📥 결과 다운로드하세요!")
                    
                    # ZIP 생성
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
                    
                    st.download_button(
                        label="📦 전체 결과 다운로드 (ZIP)",
                        data=zip_buffer,
                        file_name=f"interview_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    # 이메일 전송
                    if send_email_option and user_email:
                        with st.spinner("📧 이메일 보내는 중..."):
                            zip_buffer.seek(0)
                            attachments = [(f"interview_results_{datetime.now().strftime('%Y%m%d')}.zip", zip_buffer.read())]
                            success, msg = send_email(
                                user_email,
                                f"[캐피 인터뷰] 결과 보내드려요! - {datetime.now().strftime('%Y-%m-%d')}",
                                f"{len(text_results)}개 파일 처리 완료했어요!",
                                attachments
                            )
                            if success:
                                st.success(f"✅ {user_email}로 보내드렸어요!")
                            else:
                                st.warning(f"⚠️ 이메일 전송 실패했어요: {msg}")

if __name__ == "__main__":
    main()
