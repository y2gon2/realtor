# 부동산 AI 어드바이저 — 기획 문서 (MkDocs)

프로젝트 기획 문서를 MkDocs Material 테마로 로컬에서 열람할 수 있습니다.

## 설치

```bash
cd planning

# 가상 환경 생성 및 활성화
python3 -m venv ../../venv/mkdocs
source ../../venv/mkdocs/bin/activate

# 패키지 설치
pip install mkdocs mkdocs-material
```

## 실행

```bash
# 가상 환경 활성화 (이미 활성화된 경우 생략)
source ../../venv/mkdocs/bin/activate

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

## github page deploy

```bash
# GitHub에서 repo 생성 후 (최초 1회)
git remote add origin https://github.com/[유저명]/[레포명].git


# 내용 업데이트 시
# main 브랜치 먼저 push
git add .
git commit -m "commit contents"
git push -u origin main

# 그 다음 gh-deploy
mkdocs gh-deploy
```


## 문서 구조

```
planning/
├── mkdocs.yml          # MkDocs 설정
├── docs/               # 마크다운 문서
│   ├── index.md
│   ├── project_plan.md
│   ├── tech_research/
│   │   ├── embedding_models.md
│   │   └── vector_databases.md
└── site/               # 빌드 결과물 (git 제외)
```
