# Daily Music Video Sourcing - 2026-06-09 BRT

Scope: pick the best current RSS music/musician stories and find legal video pools for a 16:9 daily edit.

Decision rule: an asset is pipeline-ready only if the concrete video page has an explicit compatible license, press permission, or a paid editorial license. Normal YouTube, Instagram, Facebook, Yandex previews, and torrents are not pipeline-ready.

## Selected Top 5 Stories

1. Djavan cancels Angola show over sanitary context
   - RSS: G1 Pop & Arte
   - URL: https://g1.globo.com/pop-arte/noticia/2026/06/09/djavan-cancela-show-em-angola-devido-ao-contexto-sanitario-no-continente-africano.ghtml
   - Editorial angle: strongest drama/urgency among today's music items.
   - Open-video status: blocked. No relevant Commons/YouTube-CC video found.
   - Usable sourcing path:
     - Paid: Getty editorial search for Djavan performance/interview assets.
     - Paid: AP/Reuters entertainment archive if available.
     - Permission: Djavan official videos/press team.

2. Ronaldinho album "Camisa 10" with Leo Foguete and Natanzinho Lima
   - RSS: G1 Pop & Arte
   - URL: https://g1.globo.com/pop-arte/musica/blog/mauro-ferreira/post/2026/06/09/ronaldinho-gaucho-escala-leo-foguete-e-natanzinho-lima-para-representar-o-brasil-na-selecao-do-album-camisa-10.ghtml
   - Editorial angle: famous name plus music crossover.
   - Open-video status: weak. Ronaldinho has a usable Commons source, but Leo Foguete/Natanzinho Lima searches returned normal social/YouTube results without reuse permission.
   - Pipeline-ready assets already known:
     - https://commons.wikimedia.org/wiki/File:Ronaldinho_Ga%C3%BAcho_%C3%A9_escolhido_como_Embaixador_do_Turismo,_pela_Embratur.webm
   - Usable sourcing path:
     - Permission: artist/label clips from Leo Foguete and Natanzinho Lima teams.
     - Paid: Getty/AP/Reuters if they have current red-carpet/show/news footage.

3. Teresa Cristina releases "Noticia boa" / album "Tudo que eu tenho"
   - RSS: G1 Pop & Arte
   - URL: https://g1.globo.com/pop-arte/musica/blog/mauro-ferreira/post/2026/06/09/teresa-cristina-da-noticia-boa-com-cezar-mendes-entre-as-oito-musicas-autorais-do-album-tudo-que-eu-tenho.ghtml
   - Editorial angle: direct musician/album story.
   - Open-video status: blocked. Commons search found mainly an image/screenshot, not a reviewed reusable video source.
   - Usable sourcing path:
     - Paid: Getty editorial has Teresa Cristina performance coverage.
     - Permission: official press kit/label/management.
     - Conditional: EBC/TV Brasil pages only if the concrete page/video carries reuse terms and no third-party restrictions.

4. Rod Melim reworks "Inimaginavel" as acoustic audiovisual
   - RSS: G1 Pop & Arte
   - URL: https://g1.globo.com/pop-arte/musica/blog/mauro-ferreira/post/2026/06/09/rod-melim-rebobina-o-repertorio-do-album-solo-inimaginavel-em-registro-acustico-audiovisual-feito-em-estudio.ghtml
   - Editorial angle: direct musician/new audiovisual project.
   - Open-video status: blocked. Current official/Universal/YouTube results are not CC BY.
   - Usable sourcing path:
     - Permission: Rod Melim/Universal press assets.
     - Conditional: TV Brasil/Sem Censura clip only if the concrete EBC page gives compatible reuse terms.
     - Paid: Getty/AP/Reuters if available.

5. "Waka Waka", "The Cup of Life" and the formula of World Cup hits
   - RSS: G1 Pop & Arte
   - URL: https://g1.globo.com/pop-arte/musica/noticia/2026/06/09/waka-waka-the-cup-of-life-qual-e-a-formula-dos-hits-de-copa-do-mundo.ghtml
   - Editorial angle: strongest free-video candidate because Shakira has multiple open videos.
   - Open-video status: pipeline-ready for Shakira side; weak for Ricky Martin side.
   - Pipeline-ready assets already known:
     - https://commons.wikimedia.org/wiki/File:Na_ONU,_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm
     - https://commons.wikimedia.org/wiki/File:Davos_2017_-_An_Insight,_An_Idea_with_Shakira.webm
     - https://commons.wikimedia.org/wiki/File:Shakira-_They_Said_I_Sang_Like_a_Goat.webm
     - https://commons.wikimedia.org/wiki/File:Estadio_Ol%C3%ADmpico_Universitario_video.webm
   - Usable sourcing path:
     - Free: use Shakira + stadium/world-cup context.
     - Paid/permission: Ricky Martin red-carpet/interview/archive footage.

## Reserve Stories

1. Forro singers criticize fees, audience posture, and sertanejo space in Sao Joao
   - URL: https://g1.globo.com/pop-arte/musica/noticia/2026/06/09/cantores-de-forro-criticam-caches-postura-do-publico-e-espaco-do-sertanejo-no-sao-joao-do-nordeste.ghtml
   - Good drama angle, but no strong free artist-specific footage found.
   - Paid generic support: Getty has Sao Joao/Festa Junina/forro stock/editorial video pools.

2. Alcohol as artist-audience connection can hurt health/image
   - URL: https://g1.globo.com/pop-arte/sertanejo/noticia/2026/06/09/da-estrategia-de-conexao-a-crise-uso-de-alcool-para-ser-parte-do-publico-pode-prejudicar-saude-e-imagem-de-artistas.ghtml
   - Good "problem/trash/drama" angle, but needs generic sertanejo/backstage/party licensed b-roll. No direct free source found.

## Current Edit Decision

Do not force a 5-story daily video from the free whitelist today. Only the World Cup hits/Shakira story has enough open, non-repeated motion footage for a decent segment. Djavan, Teresa Cristina, Rod Melim, Leo Foguete/Natanzinho, and current forro/Sao Joao stories need paid editorial licensing or direct permission before the pipeline should use real star footage.

Recommended next system change: add a `needs_license` sourcing queue for daily multinews. The agent should save high-scoring stories that lack legal footage, show them in the dashboard, and either skip them or use a paid/permission provider once configured.

