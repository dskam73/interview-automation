import streamlit as st
import anthropic
import time
from datetime import datetime

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
        """비밀번호 검증"""
        # Streamlit Cloud의 secrets에서 비밀번호 가져오기
        correct_password = st.secrets.get("app_password", "interview2024")
        if st.session_state["password"] == correct_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 보안을 위해 비밀번호 삭제
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # 첫 실행 또는 로그아웃 상태
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
        # 비밀번호 오류
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
        # 로그인 성공
        return True

# Claude API 호출 함수
def process_with_claude(content: str, prompt: str, task_name: str) -> str:
    """Claude API를 사용하여 텍스트 처리"""
    
    # API 키 확인
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except:
        st.error("⚠️ API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
        return None
    
    client = anthropic.Anthropic(api_key=api_key)
    
    # 프로그레스 바
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
            st.error("지원하지 않는 파일 형식입니다. txt 또는 md 파일을 업로드하세요.")
            return None
    except Exception as e:
        st.error(f"파일 읽기 오류: {e}")
        return None

# 메인 앱
def main():
    # 비밀번호 체크
    if not check_password():
        return
    
    # 로그아웃 버튼 (사이드바 상단)
    with st.sidebar:
        if st.button("🚪 로그아웃"):
            st.session_state["password_correct"] = False
            st.rerun()
    
    # 헤더
    st.title("🎙️ 인터뷰 트랜스크립트 자동화 시스템")
    st.markdown("외국어 인터뷰 녹취록을 한글 트랜스크립트와 요약문으로 자동 변환합니다.")
    st.markdown("---")
    
    # 프롬프트 로드
    try:
        transcript_prompt = st.secrets["transcript_prompt"]
        summary_prompt = st.secrets["summary_prompt"]
    except Exception as e:
        st.error("⚠️ 프롬프트가 설정되지 않았습니다. 관리자에게 문의하세요.")
        st.stop()
    
    # 사이드바 - 설정
    with st.sidebar:
        st.header("⚙️ 설정")
        st.success("✅ 시스템 준비 완료")
        
        st.markdown("---")
        
        # 처리 옵션
        st.subheader("📋 처리 옵션")
        process_transcript = st.checkbox("Full 트랜스크립트 작성", value=True)
        process_summary = st.checkbox("인터뷰 요약문 작성", value=True)
        
        if not process_transcript and not process_summary:
            st.warning("⚠️ 최소 하나의 옵션을 선택하세요")
        
        st.markdown("---")
        
        # 사용 통계
        if "usage_count" not in st.session_state:
            st.session_state.usage_count = 0
        
        st.subheader("📊 현재 세션")
        st.metric("처리 횟수", st.session_state.usage_count)
        
        st.markdown("---")
        
        # 정보
        st.subheader("ℹ️ 사용 방법")
        st.markdown("""
        1. 외국어 인터뷰 녹취록 파일 업로드
        2. 처리 옵션 선택
        3. '처리 시작' 버튼 클릭
        4. 결과 확인 및 다운로드
        """)
        
        st.markdown("---")
        st.caption("v1.0 | Powered by Claude Sonnet 4")
    
    # 메인 영역 - 2열 레이아웃
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("📤 입력")
        
        # 파일 업로드
        uploaded_file = st.file_uploader(
            "녹취록 파일 선택",
            type=['txt', 'md'],
            help="외국어 인터뷰 녹취록 파일을 업로드하세요 (txt, md)"
        )
        
        # 또는 직접 입력
        st.markdown("**또는 직접 입력:**")
        direct_input = st.text_area(
            "녹취록 내용",
            height=300,
            placeholder="인터뷰 녹취록을 직접 붙여넣으세요...",
            help="파일 업로드 대신 직접 텍스트를 입력할 수 있습니다"
        )
    
    with col2:
        st.header("📊 상태")
        
        # 입력 상태
        content = None
        if uploaded_file:
            content = read_file(uploaded_file)
            if content:
                st.success(f"✅ 파일 업로드됨: {uploaded_file.name}")
                st.info(f"📄 파일 크기: {len(content):,} 자")
                
                # 미리보기
                with st.expander("📖 내용 미리보기 (처음 500자)"):
                    st.text(content[:500] + "..." if len(content) > 500 else content)
        
        elif direct_input:
            content = direct_input
            st.success("✅ 텍스트 입력 완료")
            st.info(f"📄 입력 크기: {len(content):,} 자")
        
        else:
            st.info("📁 파일을 업로드하거나 텍스트를 입력하세요")
    
    st.markdown("---")
    
    # 처리 버튼
    if content and (process_transcript or process_summary):
        col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
        with col_btn2:
            process_button = st.button("🚀 처리 시작", type="primary", use_container_width=True)
        
        if process_button:
            st.markdown("---")
            st.header("📥 처리 결과")
            
            results = {}
            
            # Full 트랜스크립트 작성
            if process_transcript:
                st.subheader("1️⃣ Full 트랜스크립트")
                with st.spinner("처리 중..."):
                    transcript_result = process_with_claude(
                        content, 
                        transcript_prompt, 
                        "Full 트랜스크립트"
                    )
                
                if transcript_result:
                    results['transcript'] = transcript_result
                    
                    # 결과 표시
                    with st.expander("📄 트랜스크립트 전체 보기", expanded=True):
                        st.markdown(transcript_result)
                    
                    # 다운로드 버튼
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.download_button(
                        label="⬇️ 트랜스크립트 다운로드",
                        data=transcript_result,
                        file_name=f"transcript_{timestamp}.md",
                        mime="text/markdown"
                    )
                    
                    st.success("✅ Full 트랜스크립트 작성 완료!")
            
            # 인터뷰 요약문 작성
            if process_summary:
                st.subheader("2️⃣ 인터뷰 요약문")
                
                # 트랜스크립트가 있으면 그것을 사용, 없으면 원본 사용
                summary_input = results.get('transcript', content)
                
                with st.spinner("처리 중..."):
                    summary_result = process_with_claude(
                        summary_input,
                        summary_prompt,
                        "인터뷰 요약문"
                    )
                
                if summary_result:
                    results['summary'] = summary_result
                    
                    # 결과 표시
                    with st.expander("📊 요약문 전체 보기", expanded=True):
                        st.markdown(summary_result)
                    
                    # 다운로드 버튼
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.download_button(
                        label="⬇️ 요약문 다운로드",
                        data=summary_result,
                        file_name=f"summary_{timestamp}.md",
                        mime="text/markdown"
                    )
                    
                    st.success("✅ 인터뷰 요약문 작성 완료!")
            
            # 사용 횟수 증가
            st.session_state.usage_count += 1
            
            # 완료 메시지
            st.balloons()
            st.success("🎉 모든 처리가 완료되었습니다!")
    
    elif content and not (process_transcript or process_summary):
        st.warning("⚠️ 처리 옵션을 최소 하나 선택하세요")

if __name__ == "__main__":
    main()
