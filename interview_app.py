import streamlit as st
import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ============================================
# Job 목록 가져오기
# ============================================

def get_all_jobs(max_age_hours=24):
    """24시간 이내 모든 Job 가져오기"""
    try:
        if not os.path.exists(JOB_DIR):
            return []
        
        jobs = []
        cutoff_time = datetime.now(KST) - timedelta(hours=max_age_hours)
        
        for job_id in os.listdir(JOB_DIR):
            job_path = os.path.join(JOB_DIR, job_id)
            if not os.path.isdir(job_path):
                continue
            
            state_file = os.path.join(job_path, 'state.json')
            if not os.path.exists(state_file):
                continue
            
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                
                # 시작 시간 체크
                start_time = datetime.fromisoformat(state.get('start_time', ''))
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=KST)
                
                if start_time < cutoff_time:
                    continue
                
                # Job 정보 구성
                jobs.append({
                    'job_id': job_id,
                    'state': state,
                    'start_time': start_time,
                    'status': state.get('status'),
                    'files': state.get('files', []),
                    'current_step': state.get('current_step'),
                    'progress': state.get('progress', 0)
                })
            except Exception:
                continue
        
        # 최신순 정렬
        jobs.sort(key=lambda x: x['start_time'], reverse=True)
        return jobs
        
    except Exception:
        return []


def format_time_ago(dt):
    """시간 경과 표시"""
    now = datetime.now(KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    
    diff = now - dt
    
    if diff < timedelta(minutes=1):
        return "방금 전"
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes}분 전"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours}시간 전"
    else:
        return dt.strftime('%m/%d %H:%M')


def get_step_display(current_step):
    """진행 단계 한글 표시"""
    step_map = {
        'init': '준비 중',
        'transcribe': '받아쓰기 중',
        'transcript': '노트정리 중',
        'summary': '요약 중',
        'zip': '파일생성 중',
        'email': '이메일발송 중',
        'done': '완료'
    }
    return step_map.get(current_step, current_step)


def get_file_display_name(files):
    """파일명 표시"""
    if not files:
        return "작업"
    
    first_file = files[0]
    if len(files) == 1:
        return first_file
    else:
        return f"{first_file} 외 {len(files)-1}개"


# ============================================
# 최근 작업물 UI
# ============================================

def show_recent_jobs():
    """최근 작업물 표시"""
    st.markdown("---")
    st.markdown("### 📥 최근 작업물 (24시간)")
    
    jobs = get_all_jobs(max_age_hours=24)
    
    if not jobs:
        st.caption("아직 작업물이 없어요. 파일을 올려주시면 열심히 정리해드릴게요! 😊")
        return
    
    # 진행 중 / 완료 분류
    processing_jobs = [j for j in jobs if j['status'] == 'processing']
    completed_jobs = [j for j in jobs if j['status'] == 'completed']
    error_jobs = [j for j in jobs if j['status'] == 'error']
    
    # 🔄 진행 중
    if processing_jobs:
        with st.expander(f"🔄 **진행 중** ({len(processing_jobs)})", expanded=True):
            for job in processing_jobs:
                job_id = job['job_id']
                files = job['files']
                start_time = job['start_time']
                current_step = job['current_step']
                progress = job['progress']
                
                display_name = get_file_display_name(files)
                time_ago = format_time_ago(start_time)
                step_text = get_step_display(current_step)
                
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.markdown(f"**📄 {display_name}**")
                    st.caption(f"⏱️ {time_ago} 시작 · {step_text} ({progress}%)")
                
                with col2:
                    if st.button("▶ 진행 상황", key=f"view_{job_id}"):
                        st.session_state.active_job_id = job_id
                        st.rerun()
                
                st.markdown("---")
    
    # ✅ 완료됨
    if completed_jobs:
        with st.expander(f"✅ **완료됨** ({len(completed_jobs)})", expanded=False):
            for job in completed_jobs:
                job_id = job['job_id']
                files = job['files']
                start_time = job['start_time']
                state = job['state']
                
                display_name = get_file_display_name(files)
                time_ago = format_time_ago(start_time)
                
                # 만료 시간 계산
                expiry_time = start_time + timedelta(hours=24)
                remaining = expiry_time - datetime.now(KST)
                hours_left = int(remaining.total_seconds() / 3600)
                
                col1, col2 = st.columns([2, 2])
                
                with col1:
                    st.markdown(f"**📄 {display_name}**")
                    st.caption(f"⏱️ {time_ago} 완료 ({hours_left}시간 남음)")
                
                with col2:
                    # 다운로드 버튼
                    zip_path = os.path.join(JOB_DIR, job_id, 'output.zip')
                    if os.path.exists(zip_path):
                        with open(zip_path, 'rb') as f:
                            zip_data = f.read()
                        
                        st.download_button(
                            "📦",
                            zip_data,
                            f"{display_name}.zip",
                            "application/zip",
                            key=f"dl_{job_id}"
                        )
                    
                    # 결과 보기 버튼
                    if st.button("▶", key=f"result_{job_id}"):
                        st.session_state.active_job_id = job_id
                        st.rerun()
                
                st.markdown("---")
    
    # ❌ 에러
    if error_jobs:
        with st.expander(f"❌ **오류 발생** ({len(error_jobs)})", expanded=False):
            for job in error_jobs:
                job_id = job['job_id']
                files = job['files']
                start_time = job['start_time']
                state = job['state']
                error_msg = state.get('error', '알 수 없는 오류')
                
                display_name = get_file_display_name(files)
                time_ago = format_time_ago(start_time)
                
                st.markdown(f"**📄 {display_name}**")
                st.caption(f"⏱️ {time_ago}")
                st.error(f"오류: {error_msg}")
                
                if st.button("🔄 다시 시도", key=f"retry_{job_id}"):
                    # TODO: 재시도 로직
                    st.info("다시 시도 기능 준비 중...")
                
                st.markdown("---")


# ============================================
# 메인 함수 수정
# ============================================

def main():
    if not check_password():
        return
    
    st.title("😊 캐피 인터뷰")
    
    # 활성 Job이 있으면 해당 화면 표시
    active_job_id = st.session_state.get('active_job_id')
    
    if active_job_id:
        job_state = load_job_state(active_job_id)
        
        if job_state:
            if job_state['status'] == 'processing':
                # 진행 중 화면
                st.markdown("꼼꼼하게 정리해 볼게요! 기대해 주세요 📎")
                show_progress_ui(job_state)
                time.sleep(HEARTBEAT_INTERVAL)
                st.rerun()
                
            elif job_state['status'] == 'completed':
                # 완료 화면
                st.markdown("퇴근하실 때 정리를 부탁하고 창을 열어두면 아침에 메일로 받아 보실 수 있어요 ^^*...")
                show_completed_ui(job_state)
                
            elif job_state['status'] == 'error':
                # 에러 화면
                st.markdown("퇴근하실 때 정리를 부탁하고 창을 열어두면 아침에 메일로 받아 보실 수 있어요 ^^*...")
                show_error_ui(job_state)
        else:
            # Job 찾을 수 없음 → 초기화
            del st.session_state['active_job_id']
            st.rerun()
    
    else:
        # 초기 화면
        st.markdown("퇴근하실 때 정리를 부탁하고 창을 열어두면 아침에 메일로 받아 보실 수 있어요 ^^*...")
        
        # 파일 업로드 UI
        uploaded_files = st.file_uploader(
            "파일 선택",
            type=['mp3', 'wav', 'm4a', 'ogg', 'webm', 'txt', 'md'],
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        
        # ... (기존 파일 업로드 로직)
        
        # 최근 작업물 표시
        show_recent_jobs()
        
        # 오늘의 사용량
        st.markdown("---")
        usage = get_daily_usage()
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"🎤 음성: {usage.get('audio', 0)}/{DAILY_LIMIT_AUDIO}개")
        with col2:
            st.caption(f"📄 텍스트: {usage.get('text', 0)}/{DAILY_LIMIT_TEXT}개")


def show_completed_ui(job_state):
    """완료 화면"""
    st.markdown("---")
    
    # 진행 단계 표시 (모두 완료)
    show_steps(len(job_state.get('steps', [])))
    
    st.success("✅ 모든 작업이 완료되었습니다!")
    
    # 통계
    col1, col2, col3 = st.columns(3)
    
    elapsed = job_state.get('elapsed_time', 0)
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    
    with col1:
        st.metric("⏱️ 소요 시간", f"{minutes}분 {seconds}초")
    with col2:
        total_files = job_state.get('total_files', 0)
        st.metric("📄 처리 파일", f"{total_files}개")
    with col3:
        total_cost = job_state.get('total_cost_krw', 0)
        st.metric("💰 비용", f"₩{total_cost:,.0f}")
    
    # 다운로드 버튼
    job_id = st.session_state.get('active_job_id')
    zip_path = os.path.join(JOB_DIR, job_id, 'output.zip')
    
    if os.path.exists(zip_path):
        with open(zip_path, 'rb') as f:
            zip_data = f.read()
        
        st.download_button(
            "📦 바로 다운로드",
            zip_data,
            f"interview_{datetime.now(KST).strftime('%y%m%d')}.zip",
            "application/zip",
            use_container_width=True
        )
    
    # 새 작업 버튼
    if st.button("🔄 새 작업 시작", use_container_width=True):
        del st.session_state['active_job_id']
        st.rerun()


def show_error_ui(job_state):
    """에러 화면"""
    st.markdown("---")
    
    error_msg = job_state.get('error', '알 수 없는 오류가 발생했습니다')
    st.error(f"❌ 작업 중 오류가 발생했습니다:\n{error_msg}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔄 다시 시도", use_container_width=True):
            # TODO: 재시도 로직
            st.info("다시 시도 기능 준비 중...")
    
    with col2:
        if st.button("🏠 처음으로", use_container_width=True):
            del st.session_state['active_job_id']
            st.rerun()


if __name__ == "__main__":
    main()
