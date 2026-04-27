# Setup do YouTube + Instagram + TikTok pelo celular (via Make.com)

Tudo aqui é feito **só pelo celular**. O Make.com tem app iOS/Android e
conexões já aprovadas com YouTube, Instagram e TikTok — você loga uma vez
em cada conta, copia uma URL de webhook, cola num secret do GitHub, e o
pipeline passa a publicar sozinho.

Tempo: ~10 minutos para o YouTube. +5 min cada para IG e TikTok.

## 1. Criar conta no Make.com

1. Abra `make.com` no navegador do celular → **Sign up free**.
2. Plano *Free* dá 1.000 operações/mês — suficiente para uns 30 vídeos/dia
   neste cenário (1 op = 1 trigger + 1 ação).

## 2. Cenário "Webhook → YouTube"

1. Dashboard → **Create a new scenario**.
2. Toque no `+` central → busque **Webhooks** → escolha
   **Custom webhook** → **Add**.
3. **Add hook** → dê um nome (ex.: `lcb-mobile`) → **Save**.
4. Copie a URL gerada (algo como
   `https://hook.eu2.make.com/abc123xyz`). Guarda essa URL.
5. Clique no `+` à direita do webhook → busque **YouTube** →
   **Upload a video**.
6. **Add connection** → faça login na sua conta Google →
   conceda permissão de upload. Pronto, autenticado.
7. Configure os campos do módulo YouTube:
   - **Title**: clique no campo, escolha do menu lateral
     `1. title` (vem do webhook).
   - **Description**: `1. long_caption` + nova linha + `Fonte: ` +
     `1. source_url`.
   - **Tags**: `1. hashtags` (Make converte array → lista).
   - **Privacy**: `Public`.
   - **Category**: `Entertainment` (24).
   - **Video file**: clique no campo, escolha
     **Map** (botão de cadeado) → cole `{{1.video_url}}`. Make baixa
     direto da URL pública do GitHub Release.
   - **Thumbnail**: opcional, use `{{1.thumbnail_url}}`.
8. Salve o cenário (botão de disquete) e ative o switch
   **ON** (canto inferior).

## 3. Adicionar Instagram Reels e TikTok ao mesmo cenário

No mesmo cenário, depois do YouTube, clique no `+` à direita →

### Instagram Reels
- Módulo: **Instagram for Business** → *Upload a Reel*.
- Connection: login na conta IG Business (precisa estar conectada a uma
  página do Facebook). Make cuida do OAuth no celular.
- Video URL: `{{1.video_url}}`. Caption:
  `{{1.headline}}\n\n{{1.short_caption}}`.

### TikTok
- Módulo: **TikTok for Business** ou **TikTok** (depende da região) →
  *Upload Video*.
- Connection: login no TikTok pelo celular. Make herda a aprovação deles.
- File: `{{1.video_url}}`. Title: `{{1.headline}}`.

> Se um módulo falhar, marque-o como **continue on error** (engrenagem →
> "Allow storing of incomplete executions") para não derrubar o cenário
> inteiro quando uma plataforma rejeitar um vídeo.

## 4. Colar a URL de webhook no GitHub

1. App GitHub → repositório → **Settings → Secrets and variables → Actions**.
2. **New repository secret**:
   - Name: `WEBHOOK_URL`
   - Value: a URL que você copiou no passo 2.4.
3. **Add secret**.

## 5. Tornar o repositório público (importante)

O webhook publisher coloca os `.mp4` em **GitHub Releases** desse repo.
Para o Make.com baixar o vídeo sem auth, o repo precisa ser **público**.

- Settings → General → Danger zone → **Change visibility** → Public.

> Se você não quiser tornar o repo público, dá pra usar a URL de download
> da API com header `Authorization: Bearer <PAT>`. Configure
> `WEBHOOK_AUTH_HEADER` no Make.com com seu PAT — mas isso adiciona um
> passo, e o objetivo aqui é simplicidade.

## 6. Disparar

GitHub mobile → **Actions** → **Cloud publish (Telegram + Make.com)** →
**Run workflow**.

Em ~3 minutos: post no Telegram + vídeo subindo nas plataformas via
Make.com. Depois disso o cron roda sozinho a cada 3 horas.

## Solução de problemas

| Erro nos logs | Causa | Conserto |
|---|---|---|
| `403 release create` | Workflow sem permissão | Já configurado em `permissions: contents: write`; confirme que não foi removido |
| `Webhook 4xx` | URL errada ou cenário desligado | Confira o switch ON no Make.com |
| `Webhook 200, mas não posta` | Cenário roda mas módulos falham | Abra o histórico do cenário no Make.com, veja qual módulo deu erro |
| Make.com baixa o vídeo `404` | Repo privado | Torne público OU use `WEBHOOK_AUTH_HEADER` com PAT |
| YouTube rejeita o título | Caracteres proibidos | O título já é gerado pelo Claude e raramente bate em filtros, mas você pode editar o módulo YouTube no Make pra cortar `>`, `<` |
