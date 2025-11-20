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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
import re
import tempfile
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# 페이지 설정
st.set_page_config(
    page_title="인터뷰 트랜스크립트 자동화",
    page_icon="🎙️",
    layout="wide"
)

# 비밀번호 보호
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
        st.markdown("팀 내부용 시스템입니다. 비밀번호를 입력하세요.")
        st.text_input(
            "비밀번호",
            type="password",
            on_change=password_entered,
            key="password"
        )
        st.info("💡 비밀번호를 모르신다면 관리자에게 문의하세요.")
        return False
    elif not st.session_state["password_correct"]:
        st.markdown("## 🔐 접근 제한")
        st.error("❌ 비밀번호가 올바르지 않습니다.")
        st.text_input(
            "비밀번호",
            type="password",
            on_change=password_entered,
            key="password"
        )
        return False
    else:
        return True

# 이메일 전송 함수
def send_email(to_email: str, subject: str, body: str, attachments: list = None):
    """이메일 전송"""
    try:
        # Gmail SMTP 설정
        gmail_user = st.secrets.get("gmail_user", None)
        gmail_password = st.secrets.get("gmail_password", None)
        
        if not gmail_user or not gmail_password:
            st.warning("⚠️ 이메일 설정이 없습니다. Secrets에 gmail_user와 gmail_password를 추가하세요.")
            return False
        
        # 이메일 구성
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # 첨부 파일
        if attachments:
            for filename, content in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename= {filename}')
                msg.attach(part)
        
        # SMTP 서버 연결 및 전송
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        text = msg.as_string()
        server.sendmail(gmail_user, to_email, text)
        server.quit()
        
        return True
    except Exception as e:
        st.error(f"이메일 전송 실패: {str(e)}")
        return False

# Whisper 전사 함수
def transcribe_audio(audio_file, model_size: str = "large-v2", task: str = "transcribe"):
    """OpenAI Whisper로 음원 전사"""
    try:
        api_key = st.secrets.get("OPENAI_API_KEY", None)
        if not api_key:
            st.error("⚠️ OpenAI API 키가 설정되지 않았습니다.")
            return None
        
        client = openai.OpenAI(api_key=api_key)
        
        # 임시 파일로 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
            tmp_file.write(audio_file.read())
            tmp_path = tmp_file.name
        
        # Whisper API 호출
        with open(tmp_path, 'rb') as audio:
            if task == "translate":
                # 영어로 번역
                transcript = client.audio.translations.create(
                    model="whisper-1",
                    file=audio
                )
            else:
                # 원어 전사
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    language=None  # 자동 감지
                )
        
        # 임시 파일 삭제
        import os
        os.unlink(tmp_path)
        
        return transcript.text
        
    except Exception as e:
        st.error(f"전사 중 오류 발생: {str(e)}")
        return None

# Claude API 호출 함수
def process_with_claude(content: str, prompt: str, task_name: str) -> str:
    """Claude API를 사용하여 텍스트 처리"""
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except:
        st.error("⚠️ API 키가 설정되지 않았습니다.")
        return None
    
    client = anthropic.Anthropic(api_key=api_key)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
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
        progress_bar.empty()
        status_text.empty()
        st.error(f"❌ 처리 중 오류 발생: {str(e)}")
        return None

# 파일 읽기 함수
def read_file(uploaded_file):
    """업로드된 파일 읽기"""
    try:
        if uploaded_file.type in ["text/plain", "text/markdown"]:
            return uploaded_file.read().decode('utf-8')
        else:
            st.error("지원하지 않는 파일 형식입니다.")
            return None
    except Exception as e:
        st.error(f"파일 읽기 오류: {e}")
        return None

# DOCX 생성 함수
def create_docx(content: str, title: str) -> io.BytesIO:
    """마크다운 텍스트를 DOCX로 변환"""
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
        elif line_stripped.startswith('#### '):
            doc.add_heading(line_stripped[5:], level=4)
        elif line_stripped.startswith('---') or line_stripped.startswith('___'):
            doc.add_paragraph('_' * 50)
        elif line_stripped.startswith('- ') or line_stripped.startswith('* ') or line_stripped.startswith('• '):
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
    """마크다운 텍스트를 PDF로 변환"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                           rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=72)
    
    styles = getSampleStyleSheet()
    story = []
    
    title_style = styles['Heading1']
    story.append(Paragraph(title, title_style))
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
    except Exception as e:
        st.warning(f"PDF 생성 중 오류: {str(e)}")
        buffer.seek(0)
        return buffer

# 메인 앱
def main():
    if not check_password():
        return
    
    with st.sidebar:
        if st.button("🚪 로그아웃"):
            st.session_state["password_correct"] = False
            st.rerun()
    
    st.title("🎙️ 인터뷰 트랜스크립트 자동화 시스템 v3.0")
    st.markdown("**음원 전사 + 여러 파일 처리 + 다양한 포맷 + 이메일 전송**")
    st.markdown("---")
    
    # 탭 생성
    tab1, tab2 = st.tabs(["📄 텍스트 파일 처리", "🎤 음원 전사"])
    
    # 프롬프트 로드
    try:
        transcript_prompt = st.secrets["transcript_prompt"]
        summary_prompt = st.secrets["summary_prompt"]
    except:
        st.error("⚠️ 프롬프트가 설정되지 않았습니다.")
        st.stop()
    
    # === TAB 1: 텍스트 파일 처리 ===
    with tab1:
        with st.sidebar:
            st.header("⚙️ 설정 - 텍스트")
            st.success("✅ 시스템 준비 완료")
            st.markdown("---")
            
            st.subheader("📋 처리 옵션")
            process_transcript = st.checkbox("Full 트랜스크립트 작성", value=True, key="text_transcript")
            process_summary = st.checkbox("인터뷰 요약문 작성", value=True, key="text_summary")
            
            st.markdown("---")
            
            st.subheader("📄 출력 포맷")
            format_md = st.checkbox("Markdown (.md)", value=True, key="text_md")
            format_docx = st.checkbox("Word (.docx)", value=True, key="text_docx")
            format_pdf = st.checkbox("PDF (.pdf)", value=False, key="text_pdf")
            
            if format_pdf:
                st.info("💡 PDF는 한글 지원 제한적")
            
            st.markdown("---")
            
            st.subheader("📧 이메일 전송")
            send_email_option = st.checkbox("결과를 이메일로 전송", value=False, key="text_email")
            if send_email_option:
                user_email = st.text_input("받을 이메일 주소", key="text_email_addr")
        
        st.header("📤 파일 업로드")
        
        uploaded_files = st.file_uploader(
            "녹취록 파일 선택 (여러 개 선택 가능)",
            type=['txt', 'md'],
            accept_multiple_files=True,
            help="Ctrl/Cmd를 누른 채로 여러 파일 선택",
            key="text_uploader"
        )
        
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)}개 파일 업로드 완료")
            
            with st.expander("📁 업로드된 파일"):
                for idx, f in enumerate(uploaded_files, 1):
                    content = read_file(f)
                    if content:
                        st.markdown(f"**{idx}. {f.name}** ({len(content):,} 자)")
        
        st.markdown("---")
        
        if uploaded_files and (process_transcript or process_summary):
            if st.button(f"🚀 {len(uploaded_files)}개 파일 일괄 처리", type="primary", use_container_width=True, key="text_process"):
                # ... 처리 로직 (앞서 작성한 코드와 동일)
                pass
    
    # === TAB 2: 음원 전사 ===
    with tab2:
        with st.sidebar:
            st.header("⚙️ 설정 - 음원")
            st.success("✅ 시스템 준비 완료")
            st.markdown("---")
            
            st.subheader("🎤 Whisper 설정")
            whisper_task = st.selectbox(
                "작업 선택",
                options=["transcribe", "translate"],
                format_func=lambda x: "전사 (원어)" if x == "transcribe" else "번역 (영어로)",
                key="whisper_task"
            )
            
            st.info("💡 **전사**: 원어 그대로 텍스트화\n💡 **번역**: 영어로 번역하여 텍스트화")
            
            st.markdown("---")
            
            st.subheader("📋 후속 처리")
            audio_process_transcript = st.checkbox("전사 후 트랜스크립트 작성", value=False, key="audio_transcript")
            audio_process_summary = st.checkbox("전사 후 요약문 작성", value=False, key="audio_summary")
            
            st.markdown("---")
            
            st.subheader("📧 이메일 전송")
            audio_send_email = st.checkbox("결과를 이메일로 전송", value=False, key="audio_email")
            if audio_send_email:
                audio_user_email = st.text_input("받을 이메일 주소", key="audio_email_addr")
        
        st.header("🎤 음원 파일 업로드")
        
        audio_files = st.file_uploader(
            "음원 파일 선택 (여러 개 선택 가능)",
            type=['mp3', 'wav', 'm4a', 'ogg', 'webm'],
            accept_multiple_files=True,
            help="지원 포맷: MP3, WAV, M4A, OGG, WEBM",
            key="audio_uploader"
        )
        
        if audio_files:
            st.success(f"✅ {len(audio_files)}개 음원 파일 업로드 완료")
            
            total_size = sum([f.size for f in audio_files])
            st.info(f"📊 총 크기: {total_size / 1024 / 1024:.2f} MB")
            
            with st.expander("📁 업로드된 파일"):
                for idx, f in enumerate(audio_files, 1):
                    st.markdown(f"**{idx}. {f.name}** ({f.size / 1024 / 1024:.2f} MB)")
        
        st.markdown("---")
        
        if audio_files:
            if st.button(f"🎤 {len(audio_files)}개 음원 전사 시작", type="primary", use_container_width=True, key="audio_process"):
                # ... 음원 처리 로직
                pass

if __name__ == "__main__":
    main()
