# 📘 Streamlit Cloud 배포 완벽 가이드

## 📋 준비물 체크리스트

- [ ] GitHub 계정
- [ ] Anthropic API 키 ([console.anthropic.com](https://console.anthropic.com)에서 발급)
- [ ] 프로젝트 지식의 두 프롬프트 파일 내용
  - Full 트랜스크립트 작성 프롬프트
  - 인터뷰 요약문 작성 프롬프트

---

## 🚀 단계별 배포 가이드

### 1단계: GitHub Repository 생성

1. [github.com](https://github.com)에 로그인
2. 우측 상단 "+" → "New repository" 클릭
3. Repository 설정:
   - **Repository name**: `interview-automation` (원하는 이름)
   - **Description**: "인터뷰 트랜스크립트 자동화 시스템"
   - **Public** 또는 **Private** 선택 (Private 권장)
   - **Add README file**: 체크 안 함 (이미 있음)
4. "Create repository" 클릭

### 2단계: 코드 업로드

#### 방법 A: GitHub 웹에서 직접 업로드 (초보자 추천)

1. 생성된 Repository 페이지에서 "uploading an existing file" 클릭
2. 다음 파일들을 드래그 앤 드롭:
   - `interview_app.py`
   - `requirements.txt`
   - `README.md`
   - `.gitignore`
3. "Commit changes" 클릭

#### 방법 B: Git 명령어 사용 (개발자용)

```bash
# 로컬에서 실행
cd /home/claude
git init
git add interview_app.py requirements.txt README.md .gitignore
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/your-username/interview-automation.git
git push -u origin main
```

### 3단계: Streamlit Cloud 배포

1. [share.streamlit.io](https://share.streamlit.io) 접속
2. GitHub 계정으로 로그인
3. "New app" 버튼 클릭
4. 설정:
   - **Repository**: `your-username/interview-automation` 선택
   - **Branch**: `main`
   - **Main file path**: `interview_app.py`
   - **App URL**: 원하는 URL (예: `interview-automation`)
5. "Deploy!" 클릭
6. 배포 진행 중... (약 2-3분 소요)

### 4단계: Secrets 설정 ⚠️ 가장 중요!

배포가 완료되면 앱이 실행되지만 오류가 발생합니다. Secrets를 설정해야 합니다.

1. Streamlit Cloud 대시보드에서 앱 클릭
2. 우측 메뉴 "⚙️ Settings" 클릭
3. "Secrets" 탭 선택
4. 아래 내용을 복사하여 붙여넣기:

```toml
# Anthropic API 키 (필수)
ANTHROPIC_API_KEY = "sk-ant-여기에_본인의_API_키_입력"

# 앱 접근 비밀번호 (필수)
app_password = "여기에_원하는_비밀번호_입력"

# Full 트랜스크립트 작성 프롬프트 (필수)
transcript_prompt = """
여기에 프로젝트 지식의 Full 트랜스크립트 프롬프트 전체 내용을 붙여넣으세요.
프롬프트가 길어도 괜찮습니다.
"""

# 인터뷰 요약문 작성 프롬프트 (필수)
summary_prompt = """
여기에 프로젝트 지식의 인터뷰 요약문 프롬프트 전체 내용을 붙여넣으세요.
프롬프트가 길어도 괜찮습니다.
"""
```

5. "Save" 클릭
6. 앱이 자동으로 재시작됩니다 (약 30초)

### 5단계: 프롬프트 내용 복사하는 방법

#### Full 트랜스크립트 프롬프트:
1. 프로젝트 지식에서 "_Full_트랜스크립트_작성_프롬프트_v2_0.txt" 파일 열기
2. 전체 내용 복사 (Ctrl+A, Ctrl+C)
3. Secrets의 `transcript_prompt = """` 와 `"""` 사이에 붙여넣기

#### 인터뷰 요약문 프롬프트:
1. 프로젝트 지식에서 "_인터뷰_요약문_작성_프롬프트_v4_0.txt" 파일 열기
2. 전체 내용 복사
3. Secrets의 `summary_prompt = """` 와 `"""` 사이에 붙여넣기

### 6단계: 테스트

1. 배포된 URL 접속 (예: `https://interview-automation.streamlit.app`)
2. 설정한 비밀번호 입력
3. 테스트 파일 업로드하여 정상 작동 확인
4. 결과 다운로드 테스트

---

## 🔧 문제 해결

### 문제 1: "API 키가 설정되지 않았습니다" 오류

**해결방법**:
1. Settings → Secrets 확인
2. `ANTHROPIC_API_KEY` 가 정확히 입력되었는지 확인
3. API 키가 유효한지 확인 ([console.anthropic.com](https://console.anthropic.com))

### 문제 2: "프롬프트가 설정되지 않았습니다" 오류

**해결방법**:
1. Secrets에 `transcript_prompt`와 `summary_prompt`가 있는지 확인
2. 따옴표(""")가 제대로 닫혔는지 확인
3. 프롬프트 내용에 """가 포함되어 있으면 이스케이프 필요

### 문제 3: 앱이 계속 재시작됨

**해결방법**:
1. Streamlit Cloud 대시보드에서 "Logs" 확인
2. 오류 메시지 확인
3. requirements.txt 버전 문제일 수 있음

### 문제 4: 비밀번호 입력 후에도 접속 안 됨

**해결방법**:
1. 브라우저 캐시 삭제 (Ctrl+Shift+Delete)
2. 시크릿 모드에서 접속 시도
3. Secrets의 `app_password` 확인

---

## 🔒 보안 체크리스트

- [ ] GitHub Repository를 Private으로 설정 (권장)
- [ ] Secrets에 API 키와 비밀번호 저장 (코드에 직접 입력 금지)
- [ ] .gitignore에 secrets.toml 포함되어 있는지 확인
- [ ] 팀원에게 비밀번호를 안전한 방법으로 전달 (Slack DM, 이메일 등)
- [ ] API 키는 절대 GitHub에 올리지 않기

---

## 📊 비용 예상

### Streamlit Cloud
- ✅ **완전 무료**
- 제한: 1개 앱, 1GB RAM, 1 CPU

### Anthropic API
예상 사용량 (파일당):
- Input: ~5,000 tokens (프롬프트 + 녹취록)
- Output: ~3,000 tokens (결과물)
- **비용**: 약 $0.05-0.10 per 파일

월 100개 파일 처리 시: **$5-10/월**

---

## 🤝 팀원과 공유하기

### 공유할 정보:
1. **앱 URL**: `https://your-app.streamlit.app`
2. **비밀번호**: (안전하게 전달)
3. **사용 가이드**: README.md 공유

### 간단한 사용 가이드 예시:

```
📧 팀원에게 보낼 메시지:

안녕하세요,

인터뷰 트랜스크립트 자동화 시스템이 준비되었습니다.

🔗 접속 URL: https://your-app.streamlit.app
🔐 비밀번호: [별도 전달]

사용 방법:
1. URL 접속 → 비밀번호 입력
2. 녹취록 파일 업로드 (txt 또는 md)
3. 처리 옵션 선택 (트랜스크립트/요약문)
4. "처리 시작" 클릭
5. 결과 다운로드

문의사항은 언제든지 연락주세요!
```

---

## 🎯 다음 단계

배포가 완료되면:

1. [ ] 실제 인터뷰 파일로 테스트
2. [ ] 팀원들에게 공유
3. [ ] 피드백 수집
4. [ ] 필요시 기능 개선

---

## 📞 도움이 필요하면

- Streamlit 공식 문서: [docs.streamlit.io](https://docs.streamlit.io)
- Anthropic API 문서: [docs.anthropic.com](https://docs.anthropic.com)
- GitHub 가이드: [docs.github.com](https://docs.github.com)

---

**성공적인 배포를 기원합니다! 🎉**
