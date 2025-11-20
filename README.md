# 🎙️ 인터뷰 트랜스크립트 자동화 시스템

외국어 인터뷰 녹취록을 한글 Full 트랜스크립트와 요약문으로 자동 변환하는 웹 애플리케이션입니다.

## 🌟 주요 기능

- ✅ 외국어 인터뷰 녹취록 → 한글 Full 트랜스크립트 자동 생성
- ✅ 한글 트랜스크립트 → 구조화된 인터뷰 요약문 자동 생성
- ✅ 비밀번호 보호로 팀 내부 전용 사용
- ✅ 파일 업로드 또는 직접 입력 지원
- ✅ 결과 즉시 확인 및 다운로드
- ✅ Claude Sonnet 4 기반 고품질 처리

## 🚀 Streamlit Cloud 배포 방법

### 1단계: GitHub에 코드 업로드

1. GitHub에서 새 Repository 생성 (예: `interview-automation`)
2. 다음 파일들을 업로드:
   - `interview_app.py`
   - `requirements.txt`
   - `README.md`

### 2단계: Streamlit Cloud 배포

1. [share.streamlit.io](https://share.streamlit.io) 접속
2. "New app" 클릭
3. GitHub Repository 선택
4. Main file: `interview_app.py` 선택
5. "Deploy!" 클릭

### 3단계: Secrets 설정

Streamlit Cloud 앱 설정에서 다음 secrets를 추가:

```toml
# .streamlit/secrets.toml

# Anthropic API 키
ANTHROPIC_API_KEY = "sk-ant-your-api-key-here"

# 앱 접근 비밀번호
app_password = "your_secure_password"

# Full 트랜스크립트 작성 프롬프트
transcript_prompt = """
[여기에 프로젝트 지식의 Full 트랜스크립트 프롬프트 전체 내용 붙여넣기]
"""

# 인터뷰 요약문 작성 프롬프트
summary_prompt = """
[여기에 프로젝트 지식의 인터뷰 요약문 프롬프트 전체 내용 붙여넣기]
"""
```

## 📝 로컬 테스트 방법

```bash
# 패키지 설치
pip install -r requirements.txt

# secrets 파일 생성
mkdir -p .streamlit
cat > .streamlit/secrets.toml << EOL
ANTHROPIC_API_KEY = "sk-ant-your-api-key"
app_password = "test123"
transcript_prompt = "[프롬프트 내용]"
summary_prompt = "[프롬프트 내용]"
EOL

# 앱 실행
streamlit run interview_app.py
```

브라우저에서 http://localhost:8501 접속

## 🔒 보안 사항

- ✅ 비밀번호로 접근 제한
- ✅ API 키는 secrets에 안전하게 저장
- ✅ GitHub에 민감한 정보 업로드 금지
- ✅ `.gitignore`에 secrets 파일 추가

## 💡 사용 방법

1. 배포된 URL 접속 (예: `https://your-app.streamlit.app`)
2. 비밀번호 입력
3. 녹취록 파일 업로드 또는 직접 입력
4. 처리 옵션 선택
5. "처리 시작" 버튼 클릭
6. 결과 확인 및 다운로드

## 🛠️ 기술 스택

- **Frontend**: Streamlit
- **AI Model**: Claude Sonnet 4 (Anthropic API)
- **Hosting**: Streamlit Cloud (무료)
- **Language**: Python 3.11+

## 📊 비용

- Streamlit Cloud: 무료
- Anthropic API: 사용량 기반 과금
  - Input: ~$3 / 1M tokens
  - Output: ~$15 / 1M tokens
  - 예상 비용: 파일당 $0.05-0.20

## 🤝 팀원 공유

1. 배포된 URL 공유
2. 비밀번호 전달 (보안 채널 사용)
3. 사용 가이드 공유

## 📞 문의

문제가 발생하면 관리자에게 문의하세요.

---

**Version**: 1.0  
**Last Updated**: 2024  
**Powered by**: Claude Sonnet 4
