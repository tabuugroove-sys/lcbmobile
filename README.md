# LCB Mobile — pipeline de fofoca BR

Pipeline automatizado em Python para um canal de "imprensa amarela" focado em
**shows, novelas, celebridades e cena DJ/eletrônica do Brasil**. Lê fontes
brasileiras, reescreve no estilo tabloide com a Anthropic API, gera Shorts
verticais (1080×1920) e publica em todos os canais com tráfego orgânico.

```
RSS (Quem, Ego, Extra, TV Foco, Hugo Gloss, Léo Dias, House Mag, Mixmag BR)
        │
        ▼
[ scraper ] → [ AI rewriter (Claude, pt-BR) ] → [ video (moviepy + ElevenLabs/gTTS) ]
                                                          │
                  ┌────────────┬──────────────┬───────────┼──────────────┐
                  ▼            ▼              ▼           ▼              ▼
              YouTube     Instagram        TikTok       X / Twitter   Telegram
              Shorts        Reels       Content API     v2 + media      Bot
```

## 🚀 Início rápido pelo celular (Telegram, ~30 min)

Tudo daqui pode ser feito apenas pelo celular. Quando estiver rodando, você
acrescenta YouTube/IG/TikTok depois, sem perder nada do que já foi postado.

1. **Bot do Telegram** — abra `@BotFather` no app, mande `/newbot`, escolha um
   nome, copie o token (`123456:ABC...`).
2. **Canal do Telegram** — crie um canal público, abra **Administradores →
   Adicionar admin**, busque pelo nome do bot e dê permissão de
   *Postar mensagens*.
3. **Anthropic** — em `console.anthropic.com` (navegador do celular), gere uma
   API key (`sk-ant-...`).
4. **(Opcional) ElevenLabs** — em `elevenlabs.io`, copie a API key. Pegue um
   `voice_id` em pt-BR na biblioteca de vozes para áudio premium. Sem isso o
   pipeline cai automaticamente no gTTS (gratuito).
5. **Fork ou clone deste repo** no GitHub pelo celular.
6. **Secrets** — no app GitHub: *Settings → Secrets and variables → Actions →
   New repository secret*. Adicione:
   - `ANTHROPIC_API_KEY` = `sk-ant-...`
   - `TELEGRAM_BOT_TOKEN` = token do @BotFather
   - `TELEGRAM_CHANNEL_ID` = `@nome_do_canal` (ou o `-100...` numérico)
   - `ELEVENLABS_API_KEY` = (opcional)
7. **(Opcional) Variables** — no mesmo lugar, aba *Variables*: `ELEVENLABS_VOICE_ID`
   com o id da voz pt-BR escolhida.
8. **Rode** — *Actions → "Telegram only (one tap)" → Run workflow*. Em ~3 min
   uma fofoca fresca cai no seu canal. Depois disso o cron principal
   ("Autopost pipeline") posta sozinho a cada 3 horas.

## ☁️ YouTube + Instagram + TikTok pelo celular (via Make.com)

YouTube/IG/TikTok não têm OAuth direto no celular, mas você pode usar o
**Make.com** (free tier) como intermediário — ele já é aprovado por
todas as plataformas. Login uma vez no app deles, copia uma URL de
webhook, cola num secret. Pronto.

1. Cria conta no `make.com`, faz cenário **Webhook → YouTube** (e
   IG/TikTok no mesmo cenário). Passo-a-passo com prints mentais em
   [`docs/MAKE_SETUP.md`](docs/MAKE_SETUP.md).
2. Adiciona o secret `WEBHOOK_URL` no GitHub.
3. Torna o repo **público** (necessário pro Make baixar o `.mp4` direto
   do GitHub Release que o pipeline cria).
4. *Actions → "Cloud publish (Telegram + Make.com)" → Run workflow*.

Esse mesmo workflow já está no cron de 3h, então depois do primeiro tap
roda sozinho.

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

## Analytics de escolha de pauta

Antes de escolher a notícia do run, o pipeline atualiza métricas dos Shorts já
publicados no YouTube (`views`, `likes`, `comments`) e ranqueia os candidatos de
RSS por fonte, categoria e palavras do título que historicamente performaram
melhor. Se ainda houver pouca amostra, ele mantém a ordem normal do RSS.

Variáveis úteis:

| Variável | Para quê |
|---|---|
| `ANALYTICS_ENABLED` | Liga/desliga o ranqueamento inteligente |
| `ANALYTICS_CANDIDATE_POOL` | Quantas notícias frescas entram na disputa |
| `ANALYTICS_HISTORY_LIMIT` | Quantos posts antigos entram no aprendizado |
| `YOUTUBE_API_KEY` | Opcional; busca métricas públicas sem depender do OAuth |
| `YOUTUBE_METRICS_REFRESH_HOURS` | Intervalo mínimo para atualizar métricas |

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
