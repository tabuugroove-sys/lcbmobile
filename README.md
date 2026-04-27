# LCB Mobile — pipeline de fofoca BR

Pipeline automatizado em Python para um canal de "imprensa amarela" focado em
**shows, novelas, celebridades e cena DJ/eletrônica do Brasil**. Lê fontes
brasileiras, reescreve no estilo tabloide com a Anthropic API, gera Shorts
verticais (1080×1920) e publica em todos os canais com tráfego orgânico.

```
RSS (Quem, Ego, Extra, TV Foco, Hugo Gloss, Léo Dias, House Mag, Mixmag BR)
        │
        ▼
[ scraper ] → [ AI rewriter (Claude, pt-BR) ] → [ video (moviepy + gTTS) ]
                                                          │
                  ┌────────────┬──────────────┬───────────┼──────────────┐
                  ▼            ▼              ▼           ▼              ▼
              YouTube     Instagram        TikTok       X / Twitter   Telegram
              Shorts        Reels       Content API     v2 + media      Bot
```

## Setup local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install -y ffmpeg fonts-dejavu-core   # Linux
cp .env.example .env  # preencha as chaves que você tem

# rodar sem publicar (apenas renderiza Shorts em ./out)
python -m scripts.run_pipeline --dry-run -v

# publicar apenas no Telegram
python -m scripts.run_pipeline --only telegram --limit 1
```

## Variáveis de ambiente

Copie de `.env.example`. Mínimo necessário para começar:

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | Reescrita do conteúdo |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHANNEL_ID` | Publicação no Telegram (mais simples para validar o pipeline) |
| `YOUTUBE_CLIENT_SECRET_FILE` | OAuth do YouTube (Data API v3) |
| `INSTAGRAM_*` | Conta Business + token Graph API + URL pública para hospedar o `.mp4` |
| `TIKTOK_*` | Token do Content Posting API |
| `TWITTER_*` | OAuth1 (necessário para upload de mídia) |

Cada publisher se desativa sozinho se não estiver configurado — não bloqueia os
outros.

## Executando 24/7

`/.github/workflows/pipeline.yml` roda a pipeline a cada 3 horas via
`schedule:` do GitHub Actions. Configure os mesmos nomes de secret no
repositório (Settings → Secrets and variables → Actions) e o estado de
deduplicação fica em cache entre execuções.

## Estrutura

```
src/
  scraper/          coleta dos RSS/HTML
  processor/        Claude rewriter (com prompt caching)
  video/            geração do Short vertical
  publisher/        um arquivo por plataforma + registry
  storage/          SQLite para deduplicação e log de posts
  pipeline.py       orquestrador
config/sources.yaml lista editável de fontes
scripts/run_pipeline.py CLI
```

## Notas editoriais

- O reescritor **não inventa fatos**: tudo que não está na fonte vira
  linguagem de rumor (`teria`, `segundo fontes`).
- O texto narrado é gerado em pt-BR e a voz vem do gTTS (com `tld=com.br`).
- Cada Short tem badge `via {Fonte}` no topo + a URL original na descrição,
  para mantermos atribuição e ficar mais seguro contra reclamações de DMCA.

## Próximos passos sugeridos

- Trocar gTTS por ElevenLabs / Azure Neural quando o volume justificar.
- Adicionar um scraper de Instagram (RSS via rssbridge) para pegar fofocas
  que só aparecem em stories.
- Painel web (FastAPI + HTMX) para revisar e editar posts antes de publicar.
