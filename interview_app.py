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
import uuid
from celery import Celery
import redis

# 문서 생성용
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ============================================
# Celery 설정
# ============================================
# Redis를 메시지 브로커로 사용
app = Celery('interview_tasks', broker='redis://localhost:6379/0')
app.conf.result_backend = 'redis://localhost:6379/0'
app.conf.task_track_started = True

# Redis 클라이언트
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# 페이지 설정 - 사이드바 숨김
st.set_page_config(
    page_title="캐피 인터뷰",
    page_icon="😊",
    layout="centered",
    initial_sidebar_state="collapsed",
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
st.markdown(
    """
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

/* 작업 상태 카드 */
.job-card {
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 1rem;
}

.job-status-running {
    border-left: 4px solid #4CAF50;
}

.job-status-pending {
    border-left: 4px solid #FFC107;
}

.job-status-completed {
    border-left: 4px solid #2196F3;
}

.job-status-failed {
    border-left: 4px solid #F44336;
}
</style>
""",
    unsafe_allow_html=True,
)

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
DOCX_FONT_NAME = "LG스마트체 Regular"
ADMIN_EMAIL_BCC = "dskam@lgbr.co.kr"
USD_TO_KRW = 1400

# ============================================
# 작업 상태 관리 함수
# ============================================
def create_job(user_emails, file_count, file_type):
    """새 작업 생성 및 ID 반환"""
    job_id = str(uuid.uuid4())
    job_data = {
        'id': job_id,
        'status': 'pending',
        'created_at': get_kst_now().isoformat(),
        'user_emails': user_emails,
        'file_count': file_count,
        'file_type': file_type,
        'progress': 0,
        'current_step': '',
        'result_file': None,
        'error': None,
        'completed_at': None
    }
    
    # Redis에 작업 정보 저장 (24시간 TTL)
    redis_client.setex(f"job:{job_id}", 86400, json.dumps(job_data))
    
    # 사용자별 작업 목록에 추가
    user_key = user_emails[0] if user_emails else "anonymous"
    redis_client.lpush(f"user_jobs:{user_key}", job_id)
    redis_client.ltrim(f"user_jobs:{user_key}", 0, 99)  # 최근 100개만 유지
    
    return job_id

def get_job_status(job_id):
    """작업 상태 조회"""
    job_data = redis_client.get(f"job:{job_id}")
    if job_data:
        return json.loads(job_data)
    return None

def update_job_status(job_id, **kwargs):
    """작업 상태 업데이트"""
    job_data = get_job_status(job_id)
    if job_data:
        job_data.update(kwargs)
        redis_client.setex(f"job:{job_id}", 86400, json.dumps(job_data))

def get_user_jobs(user_email):
    """사용자의 작업 목록 조회"""
    job_ids = redis_client.lrange(f"user_jobs:{user_email}", 0, 20)
    jobs = []
    for job_id in job_ids:
        job_data = get_job_status(job_id)
        if job_data:
            jobs.append(job_data)
    return jobs

# ============================================
# Celery 작업 정의
# ============================================
@app.task(bind=True)
def process_interview_task(self, job_id, files_data, options):
    """백그라운드에서 실행되는 인터뷰 처리 작업"""
    try:
        # 작업 시작 상태 업데이트
        update_job_status(job_id, status='running', progress=5, current_step='작업 시작')
        
        # 옵션 언패킹
        file_type = options['file_type']
        is_audio = file_type == 'audio'
        do_transcript = options['do_transcript']
        do_summary = options['do_summary']
        out_md = options['out_md']
        out_docx = options['out_docx']
        out_txt = options['out_txt']
        emails = options['emails']
        transcript_prompt = options.get('transcript_prompt', '')
        summary_prompt = options.get('summary_prompt', '')
        
        results = []
        total_audio_min = 0
        total_in_tok = 0
        total_out_tok = 0
        start_time = time.time()
        
        # 파일 처리
        for idx, file_data in enumerate(files_data):
            progress = 10 + (idx * 70 // len(files_data))
            update_job_status(job_id, progress=progress, current_step=f'파일 처리 중 ({idx+1}/{len(files_data)})')
            
            filename = file_data['name']
            content = file_data['content']
            base_name = filename.rsplit('.', 1)[0]
            
            result = {
                'filename': filename,
                'base_name': base_name,
                'whisper': None,
                'transcript': None,
                'summary': None
            }
            
            # 음성 파일 처리
            if is_audio:
                update_job_status(job_id, current_step=f'음성 인식 중: {filename}')
                # 임시 파일로 저장
                with tempfile.NamedTemporaryFile(suffix=f'.{filename.split(".")[-1]}', delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                
                # 파일 크기 확인 및 처리
                file_size_mb = len(content) / (1024 * 1024)
                if file_size_mb > MAX_FILE_SIZE_MB:
                    # 청크 분할 처리 (기존 split_audio_file 로직 사용)
                    text, duration = process_large_audio(tmp_path)
                else:
                    text, duration = transcribe_audio_file(tmp_path)
                
                os.unlink(tmp_path)
                total_audio_min += (duration or 0) / 60
                result['whisper'] = text
                source_text = text
            else:
                # 텍스트 파일 처리
                source_text = content.decode('utf-8') if isinstance(content, bytes) else content
            
            if not source_text:
                continue
            
            # 트랜스크립트 처리
            if do_transcript and transcript_prompt:
                update_job_status(job_id, current_step=f'트랜스크립트 생성 중: {filename}')
                transcript = process_with_claude_sync(source_text, transcript_prompt)
                if transcript:
                    result['transcript'] = transcript[0]
                    total_in_tok += transcript[1]
                    total_out_tok += transcript[2]
                    source_text = transcript[0] or source_text
            
            # 요약 처리
            if do_summary and summary_prompt:
                update_job_status(job_id, current_step=f'요약 생성 중: {filename}')
                summary = process_with_claude_sync(source_text, summary_prompt)
                if summary and summary[0]:
                    if result['transcript']:
                        header = extract_header_from_transcript(result['transcript'])
                        summary_text = add_header_to_summary(summary[0], header)
                    else:
                        summary_text = summary[0]
                    result['summary'] = summary_text
                    total_in_tok += summary[1]
                    total_out_tok += summary[2]
            
            results.append(result)
        
        # 결과 파일 생성
        update_job_status(job_id, progress=85, current_step='결과 파일 생성 중')
        
        if results:
            # ZIP 파일 생성
            zip_buffer = create_result_zip(results, options)
            
            # 파일 저장
            first_filename = results[0]['filename']
            zip_filename = generate_zip_filename(emails, first_filename)
            
            # 결과 파일 저장
            result_file_path = os.path.join(DOWNLOAD_DIR, f"{job_id}_{zip_filename}")
            with open(result_file_path, 'wb') as f:
                f.write(zip_buffer.getvalue())
            
            # 이메일 발송
            update_job_status(job_id, progress=95, current_step='이메일 발송 중')
            
            elapsed = time.time() - start_time
            costs = calculate_costs(total_audio_min, total_in_tok, total_out_tok)
            
            # 이메일 본문 및 첨부파일 준비
            all_attachments = prepare_email_attachments(results, options)
            all_attachments.append((zip_filename, zip_buffer.getvalue()))
            
            body = generate_email_body_for_task(
                results, len(files_data), file_type, 
                do_transcript, do_summary, options,
                int(elapsed // 60), int(elapsed % 60), costs
            )
            
            # 이메일 발송
            send_email(
