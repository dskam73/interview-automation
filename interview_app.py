import streamlit as st
import anthropic
import openai
import time
from datetime import datetime
import zipfile
import io
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
import re
import tempfile
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
from pydub import AudioSegment
import math

# 페이지 설정
st.set_page_config(
    page_title="인터뷰 트랜스크립트 자동화",
    page_icon="🎙️",
    layout="wide"
)

# 상수
MAX_FILE_SIZE = 24 * 1024 * 1024  # 24MB (여유있게 설정)
CHUNK_LENGTH_MS = 10 * 60 * 1000  # 10분 단위로 분할

# 세션 상태 초기화
if "usage_count" not in st.session_state:
    st.session_state.usage_count = 0
if "email_confirmed" not in st.session_state:
    st.session_state.email_confirmed = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

# 비밀번호 보호
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
        st.markdown("팀 내부용 시스템입니다. 비밀번호를 입력하세요.")
        st.text_input("비밀번호", type="password", on_change=password_entered, key="password")
        st.info("💡 비밀번호를 모르신다면 관리자에게 문의하세요.")
        return False
    elif not st.session_state["password_correct"]:
        st.markdown("## 🔐 접근 제한")
        st.error("❌ 비밀번호가 올바르지 않습니다.")
        st.text_input("비밀번호", type="password", on_change=password_entered, key="password")
        return False
    else:
        return True

# 이메일 전송 함수
def send_email(to_email: str, subject: str, body: str, attachments: list = None):
    try:
        gmail_user = st.secrets.get("gmail_user", None)
        gmail_password = st.secrets.get("gmail_password", None)
        
        if not gmail_user or not gmail_password:
            return False, "이메일 설정이 없습니다"
        
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        if attachments:
            for filename, content in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename= {filename}')
                msg.attach(part)
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, to_email, msg.as_string())
        server.quit()
        
        return True, "전송 성공"
    except Exception as e:
        return False, str(e)

# 오디오 파일 분할 함수
def split_audio_file(audio_file, status_container):
    """큰 오디오 파일을 청크로 분할"""
    try:
        # 임시 파일로 저장
        file_extension = audio_file.name.split('.')[-1].lower()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as tmp_file:
            tmp_file.write(audio_file.read())
            tmp_path = tmp_file.name
        
        # 파일 크기 확인
        file_size = os.path.getsize(tmp_path)
        
        if file_size <= MAX_FILE_SIZE:
            # 분할 불필요
            status_container.text("📁 파일 크기 정상 (분할 불필요)")
            return [tmp_path], False
        
        # 분할 필요
        status_container.text(f"📁 파일 크기: {file_size / 1024 / 1024:.1f}MB - 자동 분할 중...")
        
        # 오디오 로드
        if file_extension == 'm4a':
            audio = AudioSegment.from_file(tmp_path, format='m4a')
        elif file_extension == 'mp3':
            audio = AudioSegment.from_mp3(tmp_path)
        elif file_extension == 'wav':
            audio = AudioSegment.from_wav(tmp_path)
        elif file_extension == 'ogg':
            audio = AudioSegment.from_ogg(tmp_path)
        else:
            audio = AudioSegment.from_file(tmp_path)
        
        # 청크 수 계산
        total_length = len(audio)
        num_chunks = math.ceil(total_length / CHUNK_LENGTH_MS)
        
        status_container.text(f"✂️ {num_chunks}개 파트로 분할 중...")
        
        chunk_paths = []
        
        for i in range(num_chunks):
            start = i * CHUNK_LENGTH_MS
            end = min((i + 1) * CHUNK_LENGTH_MS, total_length)
            
            chunk = audio[start:end]
            
            # 청크를 임시 파일로 저장 (mp3로 변환하여 크기 감소)
            chunk_path = tempfile.mktemp(suffix='.mp3')
            chunk.export(chunk_path, format='mp3', bitrate='128k')
            
            chunk_paths.append(chunk_path)
            status_container.text(f"✂️ 분할 완료: {i+1}/{num_chunks}")
        
        # 원본 임시 파일 삭제
        os.unlink(tmp_path)
        
        status_container.text(f"✅ 분할 완료: {num_chunks}개 파트")
        
        return chunk_paths, True
        
    except Exception as e:
        status_container.error(f"분할 중 오류: {str(e)}")
        return None, False

# Whisper 전사 함수 (분할 지원)
def transcribe_audio_with_split(audio_file, task: str, progress_container):
    """OpenAI Whisper로 음원 전사 (자동 분할 지원)"""
    try:
        api_key = st.secrets.get("OPENAI_API_KEY", None)
        if not api_key:
            st.error("⚠️ OpenAI API 키가 설정되지 않았습니다.")
            return None
        
        client = openai.OpenAI(api_key=api_key)
        
        # 분할 상태 표시
        split_status = progress_container.empty()
        
        # 파일 분할
        chunk_paths, was_split = split_audio_file(audio_file, split_status)
        
        if chunk_paths is None:
            return None
        
        # 각 청크 전사
        all_transcripts = []
        total_chunks = len(chunk_paths)
        
        transcribe_progress = progress_container.progress(0)
        transcribe_status = progress_container.empty()
        
        for i, chunk_path in enumerate(chunk_paths):
            if was_split:
                transcribe_status.text(f"🎤 파트 {i+1}/{total_chunks} 전사 중...")
            else:
                transcribe_status.text(f"🎤 전사 중...")
            
            transcribe_progress.progress(int((i / total_chunks) * 100))
            
            with open(chunk_path, 'rb') as audio:
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
            
            all_transcripts.append(transcript.text)
            
            # 임시 파일 삭제
            os.unlink(chunk_path)
        
        transcribe_progress.progress(100)
        transcribe_status.text(f"✅ 전사 완료!")
        time.sleep(1)
        
        # 결과 병합
        final_transcript = '\n\n'.join(all_transcripts)
        
        # 진행률 표시 제거
        transcribe_progress.empty()
        transcribe_status.empty()
        split_status.empty()
        
        return final_transcript
        
    except Exception as e:
        st.error(f"전사 중 오류: {str(e)}")
        return None

# Claude API 호출 함수
def process_with_claude(content: str, prompt: str, task_name: str, progress_container) -> str:
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except:
        st.error("⚠️ API 키가 설정되지 않았습니다.")
        return None
    
    client = anthropic.Anthropic(api_key=api_key)
    
    progress_bar = progress_container.progress(0)
    status_text = progress_container.empty()
    
    try:
        status_text.text(f"🤖 {task_name} 처리 시작...")
        progress_bar.progress(10)
        time.sleep(1)
        
        status_text.text(f"📡 Claude API 연결 중...")
        progress_bar.progress(20)
        time.sleep(1)
        
        status_text.text(f"🔄 데이터 전송 중...")
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
        
        status_text.text(f"📝 결과 생성 중...")
        progress_bar.progress(80)
        time.sleep(1)
        
        status_text.text(f"✅ {task_name} 완료!")
        progress_bar.progress(100)
        time.sleep(1)
        
        progress_bar.empty()
        status_text.empty()
        
        return message.content[0].text
        
    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"❌ 처리 중 오류: {str(e)}")
        return None

# 파일 읽기 함수
def read_file(uploaded_file):
    try:
        if uploaded_file.type in ["text/plain", "text/markdown"]:
            return uploaded_file.read().decode('utf-8')
        else:
            return None
    except Exception as e:
        st.error(f"파일 읽기 오류: {e}")
        return None

# DOCX 생성 함수
def create_docx(content: str, title: str) -> io.BytesIO:
    doc = Document()
    
    title_paragraph = doc.add_heading(title, 0)
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    date_paragraph = doc.add_paragraph(f"생성일: {datetime.now().strftime('%Y년 %m월 %d일')}")
    date_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()
    
    lines = content.split('\n')
    
    for line in lines:
        line_stripped = line.strip()
        
        if not line_stripped:
            doc.add_paragraph()
            continue
        
        if line_stripped.startswith('# '):
            doc.add_heading(line_stripped[2:], level=1)
        elif line_stripped.startswith('## '):
            doc.add_heading(line_stripped[3:], level=2)
        elif line_stripped.startswith('### '):
            doc.add_heading(line_stripped[4:], level=3)
        elif line_stripped.startswith('---'):
            doc.add_paragraph('_' * 50)
        elif line_stripped.startswith(('- ', '* ', '• ')):
            content_text = re.sub(r'^[•\-\*]\s+', '', line_stripped)
            doc.add_paragraph(content_text, style='List Bullet')
        elif re.match(r'^\d+\.\s', line_stripped):
            content_text = re.sub(r'^\d+\.\s', '', line_stripped)
            doc.add_paragraph(content_text, style='List Number')
        elif '**' in line_stripped:
            p = doc.add_paragraph()
            parts = re.split(r'(\*\*.*?\*\*)', line_stripped)
            for part in parts:
                if part.startswith('**') and part.endswith('**'):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    p.add_run(part)
        else:
            doc.add_paragraph(line_stripped)
    
    docx_file = io.BytesIO()
    doc.save(docx_file)
    docx_file.seek(0)
    return docx_file

# PDF 생성 함수
def create_pdf_simple(content: str, title: str) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                           rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=72)
    
    styles = getSampleStyleSheet()
    story = []
    
    story.append(Paragraph(title, styles['Heading1']))
    story.append(Spacer(1, 0.3*inch))
    
    date_text = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    story.append(Paragraph(date_text, styles['Normal']))
    story.append(Spacer(1, 0.5*inch))
    
    lines = content.split('\n')
    
    for line in lines:
        line_stripped = line.strip()
        
        if not line_stripped:
            story.append(Spacer(1, 0.2*inch))
            continue
        
        if line_stripped.startswith('# '):
            story.append(Paragraph(line_stripped[2:], styles['Heading1']))
        elif line_stripped.startswith('## '):
            story.append(Paragraph(line_stripped[3:], styles['Heading2']))
        elif line_stripped.startswith('### '):
            story.append(Paragraph(line_stripped[4:], styles['Heading3']))
        elif line_stripped.startswith('---'):
            story.append(Spacer(1, 0.1*inch))
        else:
            safe_line = line_stripped.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            try:
                story.append(Paragraph(safe_line, styles['Normal']))
            except:
                pass
    
    try:
        doc.build(story)
        buffer.seek(0)
        return buffer
    except:
        buffer.seek(0)
        return buffer

# 메인 앱
def main():
    if not check_password():
        return
    
    with st.sidebar:
        if st.button("🚪 로그아웃", use_container_width=True):
            st.session_state["password_correct"] = False
            st.rerun()
        st.markdown("---")
    
    st.title("🎙️ 인터뷰 트랜스크립트 자동화 v3.1")
    st.markdown("**음성 전사 (자동 분할) + 문서 처리 + 다양한 포맷 + 이메일 전송**")
    st.markdown("---")
    
    # 프롬프트 로드
    try:
        transcript_prompt = st.secrets["transcript_prompt"]
        summary_prompt = st.secrets["summary_prompt"]
    except:
        st.error("⚠️ 프롬프트가 설정되지 않았습니다.")
        st.stop()
    
    # 탭 생성
    tab1, tab2 = st.tabs(["🎤 음성 파일 (녹취록 생성)", "📄 텍스트 파일 (녹취록 정리/번역/요약)"])
    
    # === 사이드바 ===
    with st.sidebar:
        st.header("📑 파일 선택")
        st.caption("위 탭에서 파일 유형을 선택하세요")
        st.markdown("---")
        
        st.header("⚙️ 처리 설정")
        
        # 음성 파일 설정
        with st.expander("🎤 음성 파일 모드", expanded=False):
            st.subheader("🔊 받아쓰기 방식")
            whisper_task = st.radio(
                "전사 방식",
                options=["transcribe", "translate"],
                format_func=lambda x: "원어" if x == "transcribe" else "번역(영어)",
                key="whisper_task",
                label_visibility="collapsed"
            )
            st.caption("💡 원어: 원어 그대로 / 번역: 영어로 변환")
            
            st.markdown("---")
            
            st.subheader("📋 추가 작업")
            audio_claude_transcript = st.checkbox("Claude 정리(한글)", value=False, key="audio_transcript")
            audio_claude_summary = st.checkbox("Claude 요약(한글)", value=False, key="audio_summary")
            
            st.markdown("---")
            st.info("💡 25MB 초과 파일은 자동 분할됩니다")
        
        # 텍스트 파일 설정
        with st.expander("📄 텍스트 파일 모드", expanded=True):
            st.subheader("📋 AI 정리/요약")
            text_claude_transcript = st.checkbox("Claude 정리(한글)", value=True, key="text_transcript")
            text_claude_summary = st.checkbox("Claude 요약(한글)", value=True, key="text_summary")
            
            st.markdown("---")
            
            st.subheader("📁 출력 포맷")
            format_md = st.checkbox("Markdown (.md)", value=True, key="format_md")
            format_docx = st.checkbox("Word (.docx)", value=True, key="format_docx")
            format_pdf = st.checkbox("PDF (.pdf)", value=False, key="format_pdf")
            
            if format_pdf:
                st.caption("💡 PDF는 한글 지원 제한적")
        
        st.markdown("---")
        
        # 이메일 전송
        st.header("📧 결과 전송")
        send_email_option = st.checkbox("이메일로 받기", value=False, key="send_email")
        
        if send_email_option:
            st.subheader("📮 이메일 주소")
            
            def on_email_change():
                email = st.session_state.email_input_field
                if email and "@" in email and "." in email:
                    st.session_state.email_confirmed = True
                    st.session_state.user_email = email
            
            st.text_input(
                "이메일 입력",
                value=st.session_state.get("user_email", ""),
                placeholder="example@email.com",
                key="email_input_field",
                on_change=on_email_change,
                label_visibility="collapsed"
            )
            
            if st.session_state.email_confirmed and st.session_state.user_email:
                st.success(f"✅ {st.session_state.user_email}로 결과를 보내드립니다!")
        
        st.markdown("---")
        
        st.header("📊 세션 통계")
        st.metric("처리 완료", f"{st.session_state.usage_count}개")
        
        st.markdown("---")
        st.caption("v3.1 | 자동 분할 지원")
        st.caption("Claude Sonnet 4 + OpenAI Whisper")
    
    # === TAB 1: 음성 파일 ===
    with tab1:
        st.header("🎤 음성 파일 업로드")
        st.markdown("**음성을 텍스트로 변환합니다 (녹취록 생성)**")
        st.info("💡 25MB 초과 파일은 자동으로 분할하여 처리됩니다 (파일 크기 제한 없음)")
        
        audio_files = st.file_uploader(
            "음성 파일 선택 (여러 개 가능)",
            type=['mp3', 'wav', 'm4a', 'ogg', 'webm'],
            accept_multiple_files=True,
            help="지원 포맷: MP3, WAV, M4A, OGG, WEBM (크기 제한 없음)",
            key="audio_uploader"
        )
        
        if audio_files:
            st.success(f"✅ {len(audio_files)}개 음성 파일 업로드 완료")
            
            total_size = sum([f.size for f in audio_files])
            st.info(f"📊 총 크기: {total_size / 1024 / 1024:.2f} MB")
            
            # 분할 필요 여부 표시
            large_files = [f for f in audio_files if f.size > MAX_FILE_SIZE]
            if large_files:
                st.warning(f"⚠️ {len(large_files)}개 파일이 25MB를 초과합니다. 자동 분할됩니다.")
            
            with st.expander("📁 업로드된 파일"):
                for idx, f in enumerate(audio_files, 1):
                    size_mb = f.size / 1024 / 1024
                    split_note = " ✂️ (분할 예정)" if f.size > MAX_FILE_SIZE else ""
                    st.markdown(f"**{idx}. {f.name}** ({size_mb:.2f} MB){split_note}")
        
        st.markdown("---")
        
        if audio_files:
            if st.button(f"🚀 {len(audio_files)}개 음성 파일 처리 시작", type="primary", use_container_width=True, key="audio_process"):
                
                st.markdown("---")
                st.header("📥 처리 진행 중...")
                
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                audio_results = []
                total = len(audio_files)
                
                for idx, audio_file in enumerate(audio_files, 1):
                    overall_status.markdown(f"### 🔄 진행 중: {idx}/{total} - {audio_file.name}")
                    overall_progress.progress(int((idx - 1) / total * 100))
                    
                    st.subheader(f"🎤 파일 {idx}/{total}: {audio_file.name}")
                    
                    file_progress_container = st.container()
                    
                    with file_progress_container:
                        st.markdown("**1단계: Whisper 음성 인식**")
                        
                        # 자동 분할 포함 전사
                        transcribed_text = transcribe_audio_with_split(
                            audio_file, 
                            task=whisper_task,
                            progress_container=file_progress_container
                        )
                        
                        if transcribed_text:
                            st.success("✅ 1단계 완료: 음성 전사 성공")
                            
                            result = {
                                'filename': audio_file.name,
                                'transcribed': transcribed_text,
                                'transcript': None,
                                'summary': None
                            }
                            
                            if audio_claude_transcript:
                                st.markdown("**2단계: Claude 정리(한글)**")
                                transcript_container = st.container()
                                transcript = process_with_claude(
                                    transcribed_text, 
                                    transcript_prompt, 
                                    "정리",
                                    transcript_container
                                )
                                if transcript:
                                    result['transcript'] = transcript
                                    st.success("✅ 2단계 완료: Claude 정리 성공")
                            
                            if audio_claude_summary:
                                st.markdown("**3단계: Claude 요약(한글)**")
                                summary_container = st.container()
                                summary_input = result['transcript'] if result['transcript'] else transcribed_text
                                summary = process_with_claude(
                                    summary_input,
                                    summary_prompt,
                                    "요약",
                                    summary_container
                                )
                                if summary:
                                    result['summary'] = summary
                                    st.success("✅ 3단계 완료: Claude 요약 성공")
                            
                            audio_results.append(result)
                        else:
                            st.error(f"❌ 전사 실패: {audio_file.name}")
                    
                    st.markdown("---")
                
                overall_progress.progress(100)
                overall_status.empty()
                
                st.balloons()
                st.success(f"🎉 **작업 완료!** {len(audio_results)}개 음성 파일 처리 완료")
                
                # 이메일 전송
                if send_email_option and st.session_state.user_email:
                    st.info("📧 이메일 전송 중...")
                    
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for res in audio_results:
                            base = res['filename'].rsplit('.', 1)[0]
                            if res['transcribed']:
                                zf.writestr(f"{base}_transcribed.txt", res['transcribed'])
                            if res['transcript']:
                                zf.writestr(f"{base}_transcript.md", res['transcript'])
                            if res['summary']:
                                zf.writestr(f"{base}_summary.md", res['summary'])
                    
                    zip_buffer.seek(0)
                    
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    email_success, email_message = send_email(
                        to_email=st.session_state.user_email,
                        subject=f"[인터뷰 자동화] 음성 전사 완료 - {len(audio_results)}개 파일",
                        body=f"전사 완료 시간: {timestamp}\n처리된 음원: {len(audio_results)}개",
                        attachments=[(f"audio_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip", zip_buffer.getvalue())]
                    )
                    
                    if email_success:
                        st.success(f"✅ **이메일 전송 완료!** {st.session_state.user_email}로 전송되었습니다")
                    else:
                        st.error(f"❌ **이메일 전송 실패:** {email_message}")
                
                # 다운로드
                st.markdown("---")
                st.header("⬇️ 다운로드")
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for res in audio_results:
                        base = res['filename'].rsplit('.', 1)[0]
                        if res['transcribed']:
                            zf.writestr(f"{base}_transcribed.txt", res['transcribed'])
                        if res['transcript']:
                            zf.writestr(f"{base}_transcript.md", res['transcript'])
                        if res['summary']:
                            zf.writestr(f"{base}_summary.md", res['summary'])
                
                zip_buffer.seek(0)
                st.download_button(
                    label=f"📦 전체 다운로드 (ZIP - {len(audio_results)}개 파일)",
                    data=zip_buffer,
                    file_name=f"audio_results_{timestamp}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
                
                st.session_state.usage_count += len(audio_results)
    
    # === TAB 2: 텍스트 파일 ===
    with tab2:
        st.header("📄 텍스트 파일 업로드")
        st.markdown("**텍스트를 정리하고 요약합니다 (녹취록 정리/번역/요약)**")
        
        uploaded_files = st.file_uploader(
            "텍스트 파일 선택 (여러 개 가능)",
            type=['txt', 'md'],
            accept_multiple_files=True,
            help="지원 포맷: TXT, MD",
            key="text_uploader"
        )
        
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)}개 텍스트 파일 업로드 완료")
            
            with st.expander("📁 업로드된 파일"):
                for idx, f in enumerate(uploaded_files, 1):
                    content = read_file(f)
                    if content:
                        st.markdown(f"**{idx}. {f.name}** ({len(content):,} 자)")
        
        st.markdown("---")
        
        if uploaded_files and (text_claude_transcript or text_claude_summary):
            if st.button(f"🚀 {len(uploaded_files)}개 텍스트 파일 처리 시작", type="primary", use_container_width=True, key="text_process"):
                
                st.markdown("---")
                st.header("📥 처리 진행 중...")
                
                overall_progress = st.progress(0)
                overall_status = st.empty()
                
                all_results = []
                total = len(uploaded_files)
                
                for idx, file in enumerate(uploaded_files, 1):
                    overall_status.markdown(f"### 🔄 진행 중: {idx}/{total} - {file.name}")
                    overall_progress.progress(int((idx - 1) / total * 100))
                    
                    st.subheader(f"📄 파일 {idx}/{total}: {file.name}")
                    
                    content = read_file(file)
                    if not content:
                        st.error(f"❌ 파일 읽기 실패: {file.name}")
                        continue
                    
                    result = {'filename': file.name, 'transcript': None, 'summary': None}
                    
                    if text_claude_transcript:
                        st.markdown("**1단계: Claude 정리(한글)**")
                        transcript_container = st.container()
                        transcript = process_with_claude(content, transcript_prompt, "정리", transcript_container)
                        if transcript:
                            result['transcript'] = transcript
                            st.success("✅ 1단계 완료: Claude 정리 성공")
                    
                    if text_claude_summary:
                        st.markdown("**2단계: Claude 요약(한글)**")
                        summary_container = st.container()
                        summary_input = result['transcript'] if result['transcript'] else content
                        summary = process_with_claude(summary_input, summary_prompt, "요약", summary_container)
                        if summary:
                            result['summary'] = summary
                            st.success("✅ 2단계 완료: Claude 요약 성공")
                    
                    all_results.append(result)
                    st.markdown("---")
                
                overall_progress.progress(100)
                overall_status.empty()
                
                st.balloons()
                st.success(f"🎉 **작업 완료!** {total}개 텍스트 파일 처리 완료")
                
                # 이메일 전송
                if send_email_option and st.session_state.user_email:
                    st.info("📧 이메일 전송 중...")
                    
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for res in all_results:
                            base = res['filename'].rsplit('.', 1)[0]
                            if res['transcript']:
                                if format_md:
                                    zf.writestr(f"{base}_transcript.md", res['transcript'])
                                if format_docx:
                                    docx_buf = create_docx(res['transcript'], f"{base} Transcript")
                                    zf.writestr(f"{base}_transcript.docx", docx_buf.getvalue())
                                if format_pdf:
                                    pdf_buf = create_pdf_simple(res['transcript'], f"{base} Transcript")
                                    zf.writestr(f"{base}_transcript.pdf", pdf_buf.getvalue())
                            if res['summary']:
                                if format_md:
                                    zf.writestr(f"{base}_summary.md", res['summary'])
                                if format_docx:
                                    docx_buf = create_docx(res['summary'], f"{base} Summary")
                                    zf.writestr(f"{base}_summary.docx", docx_buf.getvalue())
                                if format_pdf:
                                    pdf_buf = create_pdf_simple(res['summary'], f"{base} Summary")
                                    zf.writestr(f"{base}_summary.pdf", pdf_buf.getvalue())
                    
                    zip_buffer.seek(0)
                    
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    email_success, email_message = send_email(
                        to_email=st.session_state.user_email,
                        subject=f"[인터뷰 자동화] 처리 완료 - {total}개 파일",
                        body=f"처리 완료 시간: {timestamp}\n처리된 파일 수: {total}개",
                        attachments=[(f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip", zip_buffer.getvalue())]
                    )
                    
                    if email_success:
                        st.success(f"✅ **이메일 전송 완료!** {st.session_state.user_email}로 전송되었습니다")
                    else:
                        st.error(f"❌ **이메일 전송 실패:** {email_message}")
                
                # 다운로드
                st.markdown("---")
                st.header("⬇️ 다운로드")
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for res in all_results:
                        base = res['filename'].rsplit('.', 1)[0]
                        if res['transcript']:
                            if format_md:
                                zf.writestr(f"{base}_transcript.md", res['transcript'])
                            if format_docx:
                                docx_buf = create_docx(res['transcript'], f"{base} Transcript")
                                zf.writestr(f"{base}_transcript.docx", docx_buf.getvalue())
                            if format_pdf:
                                pdf_buf = create_pdf_simple(res['transcript'], f"{base} Transcript")
                                zf.writestr(f"{base}_transcript.pdf", pdf_buf.getvalue())
                        if res['summary']:
                            if format_md:
                                zf.writestr(f"{base}_summary.md", res['summary'])
                            if format_docx:
                                docx_buf = create_docx(res['summary'], f"{base} Summary")
                                zf.writestr(f"{base}_summary.docx", docx_buf.getvalue())
                            if format_pdf:
                                pdf_buf = create_pdf_simple(res['summary'], f"{base} Summary")
                                zf.writestr(f"{base}_summary.pdf", pdf_buf.getvalue())
                
                zip_buffer.seek(0)
                st.download_button(
                    label=f"📦 전체 다운로드 (ZIP - {len(all_results)}개 파일)",
                    data=zip_buffer,
                    file_name=f"results_{timestamp}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
                
                st.session_state.usage_count += len(all_results)

if __name__ == "__main__":
    main()
