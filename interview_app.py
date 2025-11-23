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
import multiprocessing as mp
from pathlib import Path
from typing import Optional, Dict, List, Any

# 문서 생성용
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

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
MAX_FILE_SIZE_MB = 25
USAGE_FILE = "/tmp/cappy_usage.json"
JOB_DIR = "/tmp/cappy_jobs"
DOCX_FONT_NAME = 'LG스마트체 Regular'
ADMIN_EMAIL_BCC = "dskam@lgbr.co.kr"
USD_TO_KRW = 1400

# ============================================
# Job 관리 시스템
# ============================================

class JobManager:
    """작업 관리 시스템 (백그라운드 처리)"""
    
    def __init__(self):
        self.job_dir = Path(JOB_DIR)
        self.job_dir.mkdir(exist_ok=True)
        self._cleanup_old_jobs()
    
    def _cleanup_old_jobs(self):
        """24시간 지난 작업 정리"""
        try:
            cutoff = get_kst_now() - timedelta(hours=24)
            for job_path in self.job_dir.iterdir():
                if job_path.is_dir():
                    try:
                        status_file = job_path / "status.json"
                        if status_file.exists():
                            with open(status_file, 'r') as f:
                                status = json.load(f)
                            created = datetime.fromisoformat(status.get('created_at', ''))
                            if created.tzinfo is None:
                                created = created.replace(tzinfo=KST)
                            if created < cutoff:
                                import shutil
                                shutil.rmtree(job_path)
                    except:
                        pass
        except:
            pass
    
    def create_job(self, files, user_emails, options):
        """새 작업 생성 및 파일 저장"""
        job_id = f"{get_kst_now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        job_path = self.job_dir / job_id
        job_path.mkdir(exist_ok=True)
        
        # 파일 저장
        files_dir = job_path / "files"
        files_dir.mkdir(exist_ok=True)
        
        file_list = []
        for idx, file in enumerate(files):
            file_name = f"file_{idx:03d}{Path(file.name).suffix}"
            file_path = files_dir / file_name
            with open(file_path, 'wb') as f:
                f.write(file.read())
            file.seek(0)
            file_list.append({
                'original_name': file.name,
                'saved_name': file_name,
                'size': file.size
            })
        
        # Job 정보 저장
        job_info = {
            'job_id': job_id,
            'created_at': get_kst_now().isoformat(),
            'user_emails': user_emails,
            'file_type': options.get('file_type'),
            'file_count': len(files),
            'files': file_list,
            'options': options
        }
        
        with open(job_path / "job_info.json", 'w') as f:
            json.dump(job_info, f, indent=2, ensure_ascii=False)
        
        # 초기 상태 저장
        self.update_status(job_id, {
            'status': 'queued',
            'current_file_index': 0,
            'current_stage': 'initializing',
            'progress_percent': 0,
            'completed_files': [],
            'errors': [],
            'created_at': get_kst_now().isoformat(),
            'updated_at': get_kst_now().isoformat()
        })
        
        return job_id
    
    def start_worker(self, job_id):
        """백그라운드 Worker 시작"""
        process = mp.Process(target=worker_process, args=(job_id,))
        process.start()
        return True
    
    def get_status(self, job_id):
        """작업 상태 조회"""
        try:
            status_file = self.job_dir / job_id / "status.json"
            if status_file.exists():
                with open(status_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return None
    
    def update_status(self, job_id, updates: dict):
        """작업 상태 업데이트"""
        try:
            status_file = self.job_dir / job_id / "status.json"
            
            # 기존 상태 로드
            if status_file.exists():
                with open(status_file, 'r') as f:
                    status = json.load(f)
            else:
                status = {}
            
            # 업데이트
            status.update(updates)
            status['updated_at'] = get_kst_now().isoformat()
            
            # 저장
            with open(status_file, 'w') as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"Status update error: {e}")
            return False
    
    def get_output_file(self, job_id):
        """최종 결과 파일 가져오기"""
        try:
            job_path = self.job_dir / job_id
            zip_file = job_path / "output.zip"
            if zip_file.exists():
                with open(zip_file, 'rb') as f:
                    return f.read()
        except:
            pass
        return None

# 전역 JobManager 인스턴스
job_manager = JobManager()

# ============================================
# Worker 프로세스 (별도 프로세스에서 실행)
# ============================================

def worker_process(job_id):
    """백그라운드에서 실제 작업 수행"""
    try:
        job_path = Path(JOB_DIR) / job_id
        
        # Job 정보 로드
        with open(job_path / "job_info.json", 'r') as f:
            job_info = json.load(f)
        
        # 상태 업데이트
        update_worker_status(job_id, {
            'status': 'processing',
            'started_at': get_kst_now().isoformat()
        })
        
        # 결과 디렉토리 생성
        results_dir = job_path / "results"
        results_dir.mkdir(exist_ok=True)
        
        # 파일별 처리
        files = job_info['files']
        options = job_info['options']
        total_files = len(files)
        
        total_input_tokens = 0
        total_output_tokens = 0
        total_audio_duration = 0
        
        for idx, file_info in enumerate(files):
            try:
                # 진행 상태 업데이트
                update_worker_status(job_id, {
                    'current_file_index': idx,
                    'current_file_name': file_info['original_name'],
                    'current_stage': 'starting',
                    'progress_percent': int((idx / total_files) * 100)
                })
                
                # 파일 처리
                result = process_single_file_worker(
                    job_path, 
                    file_info, 
                    idx, 
                    options, 
                    job_id
                )
                
                # 토큰 및 시간 누적
                total_input_tokens += result.get('input_tokens', 0)
                total_output_tokens += result.get('output_tokens', 0)
                total_audio_duration += result.get('audio_duration', 0)
                
                # 완료된 파일 추가
                status = get_worker_status(job_id)
                status['completed_files'].append(result)
                update_worker_status(job_id, status)
                
            except Exception as e:
                # 에러 기록
                status = get_worker_status(job_id)
                status['errors'].append({
                    'file': file_info['original_name'],
                    'error': str(e),
                    'timestamp': get_kst_now().isoformat()
                })
                update_worker_status(job_id, status)
        
        # ZIP 파일 생성
        zip_path = create_output_zip_worker(job_path, job_info, results_dir)
        
        # 비용 계산
        costs = calculate_costs_worker(
            total_audio_duration / 60,
            total_input_tokens,
            total_output_tokens,
            options.get('stt_model', 'whisper-1')
        )
        
        # 이메일 발송
        if job_info.get('user_emails'):
            send_completion_email_worker(job_info, job_path, costs)
        
        # 완료 상태 업데이트
        update_worker_status(job_id, {
            'status': 'completed',
            'progress_percent': 100,
            'completed_at': get_kst_now().isoformat(),
            'output_file': 'output.zip',
            'costs': costs
        })
        
    except Exception as e:
        # 전체 작업 실패
        update_worker_status(job_id, {
            'status': 'error',
            'error': str(e),
            'failed_at': get_kst_now().isoformat()
        })

def get_worker_status(job_id):
    """Worker에서 상태 조회"""
    try:
        status_file = Path(JOB_DIR) / job_id / "status.json"
        if status_file.exists():
            with open(status_file, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def update_worker_status(job_id, updates: dict):
    """Worker에서 상태 업데이트"""
    try:
        status_file = Path(JOB_DIR) / job_id / "status.json"
        
        if status_file.exists():
            with open(status_file, 'r') as f:
                status = json.load(f)
        else:
            status = {}
        
        status.update(updates)
        status['updated_at'] = get_kst_now().isoformat()
        
        with open(status_file, 'w') as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
        
        return True
    except:
        return False

def process_single_file_worker(job_path, file_info, idx, options, job_id):
    """Worker: 단일 파일 처리"""
    file_path = job_path / "files" / file_info['saved_name']
    result_dir = job_path / "results" / f"file_{idx:03d}"
    result_dir.mkdir(exist_ok=True)
    
    result = {
        'original_name': file_info['original_name'],
        'index': idx,
        'input_tokens': 0,
        'output_tokens': 0,
        'audio_duration': 0
    }
    
    # 1. Whisper (음성 파일인 경우)
    if options['file_type'] == 'audio':
        update_worker_status(job_id, {'current_stage': 'whisper'})
        
        # 파일 객체처럼 만들기
        class FileWrapper:
            def __init__(self, path):
                self.path = path
                self.name = path.name
                with open(path, 'rb') as f:
                    self.size = len(f.read())
            
            def read(self):
                with open(self.path, 'rb') as f:
                    return f.read()
            
            def seek(self, pos):
                pass
        
        file_obj = FileWrapper(file_path)
        text, duration = transcribe_audio_with_duration(
            file_obj,
            task=options.get('whisper_task', 'transcribe'),
            model=options.get('stt_model', 'whisper-1')
        )
        
        if text:
            whisper_path = result_dir / "whisper.txt"
            whisper_path.write_text(text, encoding='utf-8')
            result['whisper'] = str(whisper_path)
            result['audio_duration'] = duration
    else:
        # 텍스트 파일
        text = file_path.read_text(encoding='utf-8')
        result['original'] = text
    
    # 2. Transcript
    if options.get('do_transcript'):
        update_worker_status(job_id, {'current_stage': 'transcript'})
        
        transcript_prompt = get_transcript_prompt()
        transcript, in_tok, out_tok = process_with_claude_worker(
            text,
            transcript_prompt,
            "트랜스크립트"
        )
        
        if transcript:
            transcript_path = result_dir / "transcript.md"
            transcript_path.write_text(transcript, encoding='utf-8')
            result['transcript'] = str(transcript_path)
            result['input_tokens'] += in_tok
            result['output_tokens'] += out_tok
            text = transcript  # 다음 단계 입력
    
    # 3. Summary
    if options.get('do_summary'):
        update_worker_status(job_id, {'current_stage': 'summary'})
        
        summary_prompt = get_summary_prompt()
        summary, in_tok, out_tok = process_with_claude_worker(
            text,
            summary_prompt,
            "요약문"
        )
        
        if summary and result.get('transcript'):
            # 헤더 추가
            transcript_text = Path(result['transcript']).read_text(encoding='utf-8')
            header_info = extract_header_from_transcript(transcript_text)
            summary = add_header_to_summary(summary, header_info)
        
        if summary:
            summary_path = result_dir / "summary.md"
            summary_path.write_text(summary, encoding='utf-8')
            result['summary'] = str(summary_path)
            result['input_tokens'] += in_tok
            result['output_tokens'] += out_tok
    
    return result

def create_output_zip_worker(job_path, job_info, results_dir):
    """Worker: 최종 ZIP 파일 생성"""
    zip_path = job_path / "output.zip"
    options = job_info['options']
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for result_folder in results_dir.iterdir():
            if result_folder.is_dir():
                base_name = job_info['files'][int(result_folder.name.split('_')[1])]['original_name']
                base_name = Path(base_name).stem
                
                # Whisper 원본
                whisper_file = result_folder / "whisper.txt"
                if whisper_file.exists():
                    zf.write(whisper_file, f"{base_name}_whisper.txt")
                
                # Transcript
                transcript_file = result_folder / "transcript.md"
                if transcript_file.exists():
                    content = transcript_file.read_text(encoding='utf-8')
                    
                    if options.get('out_md'):
                        zf.writestr(f"{base_name}.md", content)
                    if options.get('out_docx'):
                        docx_buffer = create_docx(content, base_name)
                        zf.writestr(f"{base_name}.docx", docx_buffer.read())
                    if options.get('out_txt'):
                        plain = re.sub(r'[#*_\-]+', '', content)
                        zf.writestr(f"{base_name}.txt", re.sub(r'\n{3,}', '\n\n', plain))
                
                # Summary
                summary_file = result_folder / "summary.md"
                if summary_file.exists():
                    content = summary_file.read_text(encoding='utf-8')
                    
                    if options.get('out_md'):
                        zf.writestr(f"#{base_name}.md", content)
                    if options.get('out_docx'):
                        docx_buffer = create_docx(content, f"#{base_name}")
                        zf.writestr(f"#{base_name}.docx", docx_buffer.read())
                    if options.get('out_txt'):
                        plain = re.sub(r'[#*_\-]+', '', content)
                        zf.writestr(f"#{base_name}.txt", re.sub(r'\n{3,}', '\n\n', plain))
    
    return zip_path

def send_completion_email_worker(job_info, job_path, costs):
    """Worker: 완료 이메일 발송"""
    try:
        # 이메일 본문 생성
        body = generate_email_body_worker(job_info, costs)
        
        # ZIP 파일 첨부
        zip_path = job_path / "output.zip"
        zip_data = zip_path.read_bytes()
        
        # 파일명 생성
        first_file = job_info['files'][0]['original_name']
        zip_filename = generate_zip_filename(job_info['user_emails'], first_file)
        
        # 이메일 발송
        send_email(
            job_info['user_emails'],
            f"[캐피 인터뷰] 인터뷰 정리 완료 - {Path(first_file).stem}",
            body,
            [(zip_filename, zip_data)]
        )
    except Exception as e:
        print(f"Email send error: {e}")

def generate_email_body_worker(job_info, costs):
    """Worker: 이메일 본문 생성"""
    files = job_info['files']
    options = job_info['options']
    
    file_list = "\n".join([f"{i+1}. {f['original_name']}" for i, f in enumerate(files)])
    
    tasks = []
    if options['file_type'] == 'audio':
        tasks.append("받아쓰기")
    if options.get('do_transcript'):
        tasks.append("정리")
    if options.get('do_summary'):
        tasks.append("요약")
    
    task_desc = ", ".join(tasks)
    
    body = f"""안녕하세요! 캐피입니다 😊
인터뷰 정리 결과를 보내드립니다.

📄 다음 파일들을 처리했습니다 ({len(files)}개)
─────────────────────────────────────────
{file_list}

✅ {task_desc}를 완료했습니다

※ 첨부파일을 확인해주세요!

💰 처리 비용: 약 {costs['total_krw']:,.0f}원

오늘도 좋은 하루 되세요 😃
캐피가 드립니다.

{get_kst_now().strftime('%Y. %m/%d (%H:%M)')}
"""
    return body

# ============================================
# 오디오 처리
# ============================================

def get_audio_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(file_path)]
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
        ext = Path(audio_file.name).suffix.lower()
        input_path = os.path.join(temp_dir, f"input{ext}")
        
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

def transcribe_audio_with_duration(audio_file, task="transcribe", model="whisper-1"):
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            return None, 0
        
        client = openai.OpenAI(api_key=api_key)
        file_size_mb = audio_file.size / (1024 * 1024)
        
        # 번역은 whisper-1만 지원
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
                        result = client.audio.translations.create(
                            model="whisper-1",
                            file=("chunk.mp3", chunk['data'], "audio/mpeg")
                        )
                    else:
                        result = client.audio.transcriptions.create(
                            model=model,
                            file=("chunk.mp3", chunk['data'], "audio/mpeg")
                        )
                    all_text.append(result.text)
                except:
                    continue
            
            return "\n\n".join(all_text), total_duration
        else:
            ext = Path(audio_file.name).suffix.lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
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
    except:
        return None, 0

# ============================================
# Claude 처리
# ============================================

def process_with_claude_worker(content, prompt, task_name):
    """Worker: Claude API 호출"""
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
# 프롬프트 로드
# ============================================

def get_transcript_prompt():
    try:
        return st.secrets.get("transcript_prompt", "")
    except:
        return ""

def get_summary_prompt():
    try:
        return st.secrets.get("summary_prompt", "")
    except:
        return ""

# ============================================
# 파일 처리 유틸리티
# ============================================

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
    if not summary or summary.strip().startswith('# '):
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
    base = Path(source).stem
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

def calculate_costs_worker(audio_min, in_tok, out_tok, stt_model):
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
# 메인 앱
# ============================================

def main():
    if not check_password():
        return
    
    st.markdown("# 😊 캐피 인터뷰")
    
    # 진행 중인 작업 확인
    if 'current_job_id' in st.session_state:
        job_id = st.session_state.current_job_id
        status = job_manager.get_status(job_id)
        
        if status and status['status'] in ['queued', 'processing']:
            display_job_progress(job_id, status)
            return
        elif status and status['status'] == 'completed':
            display_job_completed(job_id, status)
            return
        elif status and status['status'] == 'error':
            display_job_error(job_id, status)
            return
    
    # 새 작업 시작 UI
    st.markdown("인터뷰를 정리하는 캐피입니다. 음성/텍스트를 올려주세요! 🔎")
    st.markdown("---")
    
    # 파일 업로드
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
        
        is_audio = any(Path(f.name).suffix[1:].lower() in audio_exts for f in uploaded_files)
        is_text = any(Path(f.name).suffix[1:].lower() in text_exts for f in uploaded_files)
        
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
                        whisper_task = st.radio(
                            "받아쓰기 방식",
                            ["원어 그대로", "영어로 번역"],
                            label_visibility="collapsed"
                        )
                        do_transcript = st.checkbox("노트 정리", value=True)
                    else:
                        whisper_task = "원어 그대로"
                        do_transcript = st.checkbox("풀 트랜스크립트", value=True)
                    do_summary = st.checkbox("요약문 작성", value=False)
                
                with col2:
                    st.markdown("**📄 출력 형식**")
                    out_md = st.checkbox("Markdown", value=True)
                    out_docx = st.checkbox("Word", value=True)
                    out_txt = st.checkbox("Text", value=False)
                
                # 음성 파일일 때 모델 선택
                if is_audio:
                    st.markdown("---")
                    st.markdown("**🎤 음성 인식 모델**")
                    stt_model = st.radio(
                        "모델 선택",
                        options=["gpt-4o-transcribe", "whisper-1", "gpt-4o-mini-transcribe"],
                        format_func=lambda x: {
                            "gpt-4o-transcribe": "GPT-4o ($0.006/분) - 최고 정확도",
                            "whisper-1": "Whisper ($0.006/분) - 안정적",
                            "gpt-4o-mini-transcribe": "GPT-4o Mini ($0.003/분) - 50% 저렴"
                        }[x],
                        index=0,
                        label_visibility="collapsed"
                    )
                else:
                    stt_model = "whisper-1"
                
                st.markdown("---")
                
                # 이메일 입력 (필수)
                st.markdown("**📧 결과 받을 이메일** (필수)")
                email_input = st.text_input(
                    "이메일 주소 (콤마로 구분, 최대 5명)",
                    placeholder="user@company.com",
                    label_visibility="collapsed"
                )
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
                    options = {
                        'file_type': file_type,
                        'whisper_task': 'translate' if whisper_task == "영어로 번역" else 'transcribe',
                        'do_transcript': do_transcript,
                        'do_summary': do_summary,
                        'out_md': out_md,
                        'out_docx': out_docx,
                        'out_txt': out_txt,
                        'stt_model': stt_model
                    }
                    
                    job_id = job_manager.create_job(files, emails, options)
                    st.session_state.current_job_id = job_id
                    
                    # 사용량 업데이트
                    update_usage(file_type, len(files))
                    
                    # Worker 시작
                    job_manager.start_worker(job_id)
                    
                    st.rerun()
    
    # 사용량 표시
    st.markdown("---")
    usage = get_daily_usage()
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"🎤 음성: {usage.get('audio', 0)}/{DAILY_LIMIT_AUDIO}개")
    with col2:
        st.caption(f"📄 텍스트: {usage.get('text', 0)}/{DAILY_LIMIT_TEXT}개")

def display_job_progress(job_id, status):
    """작업 진행 중 화면"""
    st.markdown("꼼꼼하게 정리해 볼게요! 기대해 주세요 🔎")
    st.markdown("---")
    
    st.info("""
    🔨 작업이 진행 중입니다!
    
    ✅ 이 화면을 닫거나 새로고침해도 작업은 계속됩니다
    ✅ 완료되면 이메일로 결과를 받으실 수 있습니다
    ✅ 이 페이지에서도 계속 확인 가능합니다
    
    💡 예상 소요 시간: 파일당 약 2-5분
    """)
    
    # 진행 상태
    progress = status.get('progress_percent', 0)
    st.progress(progress / 100)
    
    current_file = status.get('current_file_name', '')
    current_stage = status.get('current_stage', '')
    
    stage_name = {
        'initializing': '준비 중',
        'whisper': '받아쓰기',
        'transcript': '정리',
        'summary': '요약'
    }.get(current_stage, current_stage)
    
    if current_file:
        st.caption(f"📄 {current_file} - {stage_name} 중...")
    
    st.caption(f"📊 진행률: {progress}%")
    
    # 완료된 파일
    completed = len(status.get('completed_files', []))
    if completed > 0:
        st.caption(f"✅ {completed}개 파일 완료")
    
    # 2초 후 자동 새로고침
    time.sleep(2)
    st.rerun()

def display_job_completed(job_id, status):
    """작업 완료 화면"""
    st.success("✅ 완료! 이메일로 결과를 보냈어요.")
    
    # 통계
    costs = status.get('costs', {})
    completed_files = status.get('completed_files', [])
    
    col1, col2, col3 = st.columns(3)
    with col1:
        started = datetime.fromisoformat(status['started_at'])
        completed = datetime.fromisoformat(status['completed_at'])
        elapsed = (completed - started).total_seconds()
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        st.metric("⏱️ 소요 시간", f"{minutes}분 {seconds}초")
    with col2:
        st.metric("📄 처리 파일", f"{len(completed_files)}개")
    with col3:
        st.metric("💰 비용", f"₩{costs.get('total_krw', 0):,.0f}")
    
    # 다운로드
    zip_data = job_manager.get_output_file(job_id)
    if zip_data:
        st.markdown("---")
        st.download_button(
            "📦 바로 다운로드",
            zip_data,
            status.get('output_file', 'output.zip'),
            "application/zip",
            use_container_width=True
        )
    
    # 새 작업 버튼
    if st.button("🔄 새 작업 시작", use_container_width=True):
        del st.session_state.current_job_id
        st.rerun()

def display_job_error(job_id, status):
    """작업 오류 화면"""
    st.error(f"⚠️ 오류 발생: {status.get('error', '알 수 없는 오류')}")
    
    # 부분 완료된 파일
    completed = status.get('completed_files', [])
    if completed:
        st.info(f"💡 {len(completed)}개 파일은 정상 처리되었습니다.")
    
    # 다시 시도
    if st.button("🔄 새로 시작", use_container_width=True):
        del st.session_state.current_job_id
        st.rerun()

if __name__ == "__main__":
    # multiprocessing을 위한 설정
    mp.set_start_method('spawn', force=True)
    main()
