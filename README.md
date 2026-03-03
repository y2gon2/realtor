# 부동산 AI 어드바이저 — 기획 문서 (MkDocs)

프로젝트 기획 문서를 MkDocs Material 테마로 로컬에서 열람할 수 있습니다.

## 설치

```bash
cd planning

# 가상 환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate

# 패키지 설치
pip install mkdocs mkdocs-material
```

## 실행

```bash
# 가상 환경 활성화 (이미 활성화된 경우 생략)
source .venv/bin/activate

# 로컬 개발 서버 시작 (http://127.0.0.1:8000)
mkdocs serve
```

브라우저에서 http://127.0.0.1:8000 접속.
문서를 수정하면 자동으로 새로고침됩니다.

## 정적 사이트 빌드

```bash
mkdocs build
```

빌드 결과는 `site/` 디렉토리에 생성됩니다.

## 문서 구조

```
planning/
├── mkdocs.yml          # MkDocs 설정
├── docs/               # 마크다운 문서
│   ├── index.md
│   ├── project_plan.md
│   └── embedding_models.md
└── site/               # 빌드 결과물 (git 제외)
```
