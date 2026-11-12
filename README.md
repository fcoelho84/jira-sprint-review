# Jira Sprint Report

App **local e gratuito** que gera relatório de sprint a partir do **Jira Rovo**, permite revisar o texto, monta **slides PPTX** e um **vídeo MP4 narrado** em português.

Interface em **HTML/CSS/JS puro** + API **FastAPI** — sem Streamlit e sem telemetria de UI.

## O que faz

1. Abre o Chromium (Playwright) para você logar no Jira e **extrai a sessão sozinha**
2. Conversar com o **Rovo** (endpoint SSE interno) pedindo o que foi feito na sprint
3. Você **seleciona o board** (obrigatório) — o Rovo recebe o nome do board para focar a sprint certa
4. Permite editar o relatório e pedir mudanças ao Rovo
5. Gera slides (PPTX + preview PNG) com texto limpo (sem Markdown cru)
6. Baixa **imagens/vídeos** dos anexos e comentários das tasks (via API Jira) e usa como ilustração nos slides; em vídeo, extrai o 1º frame
7. Gera áudio com **edge-tts** (pt-BR) e monta **MP4** (slide + narração)

A geração de vídeo roda em **thread no servidor**: fechar a aba não cancela o job; ao voltar, o status/arquivo aparecem.

## Stack

| Camada | Tecnologia | Papel |
| --- | --- | --- |
| UI | HTML + CSS + JS vanilla (`apps/web/`) | Wizard em 4 etapas, sem framework frontend |
| API | FastAPI + Uvicorn | REST local (`server.py` → `presentation/`) |
| Auth Jira | Playwright (Chromium persistente) | Login manual + captura de cookies HttpOnly |
| Relatório | Rovo Chat SSE (`httpx`) | Prompt multi-turno com `conversation_id` |
| Estrutura | Python puro (`application/report_structurer`) | Markdown → slides + limpeza de formatação |
| Slides | `python-pptx` + Pillow | PPTX editável + PNG para preview/vídeo |
| TTS | `edge-tts` | Vozes neurais pt-BR gratuitas (sem API key) |
| Vídeo | MoviePy + `imageio-ffmpeg` | Concatena PNG + MP3 → MP4 H.264 |
| Config | `.env` + `python-dotenv` | URL, cloud id, agent id (sem cookie) |
| Runtime | Python 3.12 (`uv`) | Ambiente isolado em `.venv` |

### Dependências principais

- `fastapi`, `uvicorn`, `jinja2`, `python-multipart` — servidor HTTP
- `httpx` — cliente SSE do Rovo
- `playwright` — browser de login
- `python-pptx`, `Pillow` — slides
- `edge-tts` — narração
- `moviepy`, `imageio-ffmpeg` — vídeo
- `markdown` — preview HTML do relatório
- `python-dotenv` — config

## Estrutura do projeto (clean architecture simples)

```
jira-sprint-report/
├── server.py
├── apps/
│   ├── web/                       # UI (HTML/CSS/JS)
│   └── jira_sprint_report/
│       ├── domain/                # models + ports
│       ├── application/           # use cases, prompt, structurer, state
│       ├── infrastructure/        # adapters (Rovo, Playwright, Jira, slides, TTS, vídeo)
│       └── presentation/          # FastAPI routes + schemas
├── prompts/sprint_report.txt
├── output/
├── .env.example
└── requirements.txt
```

Novos adapters (ex.: outro TTS ou renderer) implementam um `Protocol` em `domain/ports.py`
e são plugados em `application/services.py` / `infrastructure/adapters.py` — sem mudar a API.

## Setup

```bash
cd jira-sprint-report
uv python install 3.12
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt

# Chromium do Playwright (fica em .playwright-browsers/)
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers"
playwright install chromium

cp .env.example .env
```

No `.env` configure só:

- `JIRA_BASE_URL`
- `JIRA_CLOUD_ID`
- `ROVO_AGENT_ID`
- `TTS_VOICE` (opcional)

O board é escolhido na UI (não fica no `.env`).

**Não** coloque cookie no `.env`.

## Rodar

```bash
source .venv/bin/activate
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers"
python server.py
```

Abra: **http://localhost:8501**

### Fluxo na UI

1. **Fazer login no Jira** → logue no Chromium → sessão salva em `.cookies.json` + `.browser-profile/`
2. **Selecionar o board** (obrigatório) → lista via API Agile
3. **Gerar relatório** → Rovo foca a sprint do board escolhido
4. **Revisar** → edite ou peça mudanças → aprove
5. **Slides** → PPTX + preview
6. **Vídeo** → TTS + MP4 (job em background)

Saídas em `output/<timestamp>/` (`report.md`, `slides/`, `audio/`, `sprint-report.pptx`, `sprint-report.mp4`).

## Endpoints úteis

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/` | UI |
| GET | `/api/state` | Estado atual / status do job |
| GET | `/api/boards` | Lista boards do Jira (precisa de sessão) |
| POST | `/api/board` | Define o board selecionado |
| POST | `/api/login` | Abre Chromium e captura sessão |
| POST | `/api/report` | Gera relatório via Rovo |
| POST | `/api/revise` | Follow-up no mesmo chat |
| POST | `/api/approve` | Estrutura slides |
| POST | `/api/slides` | Gera PPTX/PNG |
| POST | `/api/video` | Inicia job de vídeo |
| GET | `/files/...` | Download de artefatos |

## Sessão / segurança

- Cookies e perfil do browser são locais e estão no `.gitignore`
- O chat do Rovo usa API **interna** do Atlassian (mesmo fluxo do browser); pode mudar
- Use só na sua máquina / rede confiável — a API não tem autenticação própria

## Avisos

- Selecione o board certo na UI — o nome vai no prompt do Rovo
- Primeira geração de vídeo pode demorar (TTS + encode)
- Não commite `.env`, `.cookies.json`, `.browser-profile/`, `.playwright-browsers/`
